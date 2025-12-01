from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Collect all submodules under the `plugins` package so PyInstaller includes them
hiddenimports = collect_submodules('plugins')
# Include plugin data files (e.g., external binaries/metadata)
datas = collect_data_files('plugins')
