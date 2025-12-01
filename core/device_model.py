from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex, QVariant


class DeviceTableModel(QAbstractTableModel):
    """A lightweight, efficient table model for large device lists.

    Each device is represented as a dict with keys:
      - id
      - ip
      - hostname
      - os
      - status
      - last_ping
      - target ("{ip}:{id}")

    The model exposes simple methods to insert, update (or insert), remove by
    target, and retrieve devices. It emits the proper signals so the view
    remains responsive for large row counts.
    """

    COLUMNS = ["IP Address", "Host Name", "OS", "Status", "Last Ping", "Bot ID"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices = []
        self._target_index = {}  # target -> index into _devices

    def rowCount(self, parent=QModelIndex()):
        return len(self._devices)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return QVariant()
        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._devices):
            return QVariant()
        device = self._devices[row]
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return device.get('ip', 'Unknown')
            elif col == 1:
                return device.get('hostname', 'Unknown')
            elif col == 2:
                return device.get('os', 'Unknown')
            elif col == 3:
                return device.get('status', 'Disconnected')
            elif col == 4:
                return device.get('last_ping', 'N/A')
            elif col == 5:
                return device.get('id', '')
        return QVariant()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return QVariant()
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.COLUMNS):
                return self.COLUMNS[section]
        return QVariant()

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    # Convenience API
    def device_count(self):
        return len(self._devices)

    def device_at(self, row):
        if 0 <= row < len(self._devices):
            return self._devices[row]
        return None

    def find_index_by_target(self, target):
        return self._target_index.get(target, -1)

    def begin_insert_device(self, position):
        self.beginInsertRows(QModelIndex(), position, position)

    def end_insert_device(self):
        self.endInsertRows()

    def insert_device(self, device):
        # append to end
        position = len(self._devices)
        self.beginInsertRows(QModelIndex(), position, position)
        self._devices.append(device)
        self._target_index[device['target']] = position
        self.endInsertRows()

    def update_or_insert(self, device):
        """Update an existing device by target, or insert it if missing.

        Returns a tuple (action, row) where action is 'updated' or 'inserted'.
        """
        target = device.get('target')
        if target is None:
            # cannot proceed without target
            return (None, -1)
        idx = self._target_index.get(target)
        if idx is not None:
            # update and emit dataChanged
            self._devices[idx].update(device)
            left = self.index(idx, 0)
            right = self.index(idx, self.columnCount() - 1)
            self.dataChanged.emit(left, right, [])
            return ('updated', idx)
        else:
            # insert
            position = len(self._devices)
            self.beginInsertRows(QModelIndex(), position, position)
            self._devices.append(device.copy())
            self._target_index[target] = position
            self.endInsertRows()
            return ('inserted', position)

    def remove_by_target(self, target):
        idx = self._target_index.get(target)
        if idx is None:
            return False
        self.beginRemoveRows(QModelIndex(), idx, idx)
        self._devices.pop(idx)
        self.endRemoveRows()
        # rebuild index map (cheap relative to removal cost)
        self._target_index = {d['target']: i for i, d in enumerate(self._devices)}
        return True

    def clear(self):
        if not self._devices:
            return
        self.beginResetModel()
        self._devices.clear()
        self._target_index.clear()
        self.endResetModel()

    def load_devices(self, devices):
        self.beginResetModel()
        self._devices = [d.copy() for d in devices]
        self._target_index = {d['target']: i for i, d in enumerate(self._devices)}
        self.endResetModel()


class DeviceTableShim:
    """Compatibility shim that exposes a subset of the old QTableWidget
    API while delegating rendering/selection to a QTableView backed by
    DeviceTableModel.

    The application sets `self.device_view` to the real QTableView and
    `self.device_table` to an instance of this shim so older plugins that
    call `parent.device_table.item(...)` or `setRowCount(0)` continue to work.
    """

    class _Item:
        def __init__(self, text):
            self._text = text or ''

        def text(self):
            return str(self._text)

    def __init__(self, view, model):
        self._view = view
        self._model = model
        # expose commonly-used view signals/attributes
        self.customContextMenuRequested = getattr(self._view, 'customContextMenuRequested', None)

    def __getattr__(self, name):
        # forward unknown attributes to the underlying QTableView
        return getattr(self._view, name)

    # Compatibility methods expected by plugins
    def rowCount(self):
        return self._model.rowCount()

    def setRowCount(self, n):
        if n == 0:
            self._model.clear()

    def item(self, row, col):
        device = self._model.device_at(row)
        if not device:
            return None
        mapping = {0: 'ip', 1: 'hostname', 2: 'os', 3: 'status', 4: 'last_ping', 5: 'id'}
        key = mapping.get(col)
        return DeviceTableShim._Item(device.get(key))

    def setItem(self, row, col, qtablewidgetitem):
        # qtablewidgetitem is expected to have .text() method
        device = self._model.device_at(row)
        if not device:
            return
        val = qtablewidgetitem.text() if hasattr(qtablewidgetitem, 'text') else str(qtablewidgetitem)
        mapping = {0: 'ip', 1: 'hostname', 2: 'os', 3: 'status', 4: 'last_ping', 5: 'id'}
        key = mapping.get(col)
        if key:
            device[key] = val
            # if id or ip changed, update target
            if key in ('id', 'ip'):
                device['target'] = f"{device.get('ip','Unknown')}:{device.get('id','') }"
            self._model.update_or_insert(device)

    def insertRow(self, row):
        # No-op for view-backed model; append an empty placeholder
        self._model.insert_device({'id': '', 'ip': '', 'hostname': '', 'os': '', 'status': 'Disconnected', 'last_ping': 'N/A', 'target': f':'})

    def removeRow(self, row):
        device = self._model.device_at(row)
        if not device:
            return
        self._model.remove_by_target(device.get('target'))

    def setRowHidden(self, row, hide=True):
        try:
            self._view.setRowHidden(row, hide)
        except Exception:
            pass

    def selectedItems(self):
        # Return items for the first selected row to mimic QTableWidget.selectedItems()
        sel = self._view.selectionModel().selectedRows()
        items = []
        if not sel:
            return items
        row = sel[0].row()
        for col in range(self._model.columnCount()):
            items.append(DeviceTableShim._Item(self._model.device_at(row).get(['ip','hostname','os','status','last_ping','id'][col])))
        return items

    def currentRow(self):
        sel = self._view.selectionModel().selectedRows()
        if sel:
            return sel[0].row()
        return -1
