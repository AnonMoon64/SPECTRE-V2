SPECTRE Scaling Notes
=====================

Scope
-----
This document summarizes practical limits of a single-process GUI (PyQt) connected to a single MQTT broker for managing very large fleets (10k–500k devices) and recommends approaches for scaling.

Key constraints
---------------
- GUI memory: Each device row consumes model memory; with a lightweight model/view the per-row cost can be reduced (dozens of bytes), but 100k+ rows will still require multiple MBs.
- Network throughput: MQTT broker limits and client library behavior affect the rate of pings and message dispatch.
- Broker load: A single broker instance may not handle hundreds of thousands of small messages and many retained topics reliably without clustering or sharding.
- UI responsiveness: Frequent UI updates (per-device timers, many dataChanged events) can cause the GUI thread to stall if not batched.

Recommendations
---------------
1. Model/View & batching
   - Keep the UI backed by a minimal `QAbstractTableModel` and avoid widget-per-row. Batch UI updates and apply them on a timer (as in the current implementation).

2. Presence aggregation
   - Offload presence checking to an external worker or service. The GUI should request summaries (e.g., "how many connected in this shard") and only fetch details on demand.

3. Broker architecture
   - Use broker clustering (e.g., EMQX, VerneMQ, Mosquitto with federation) or managed cloud brokers that scale horizontally.
   - Partition devices by topic namespace and run multiple aggregators/GUI instances each responsible for a shard.

4. Backend aggregation + websockets
   - Implement a lightweight backend service that subscribes to the broker, aggregates messages, and exposes WebSocket/HTTP endpoints to the GUI. The GUI then subscribes to summarized streams instead of raw device topics.

5. Telemetry pipeline
   - For telemetry at scale, use a streaming pipeline (Kafka, NATS) and short-lived consumers that aggregate metrics and write summaries to a datastore (InfluxDB, Prometheus + TSDB).

6. Pagination & virtualized views
   - Implement virtualized table views and pagination so the GUI only materializes visible rows plus a small buffer.

Operational guidance
--------------------
- Start with a single broker for <= 10k devices, but monitor broker CPU and message latency.
- For 10k–100k devices, shard by region or customer and run an aggregator per shard.
- For >100k devices, use a telemetry pipeline and multiple aggregator/GUI instances; use read replicas for historical queries.

Conclusion
----------
SPECTRE's current model/view and batched presence approach scales well to 10k devices on a single process. For larger scales adopt sharding and backend aggregation to avoid overloading the broker or GUI.
