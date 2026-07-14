# Deploying on Streamlit Community Cloud

The previous `ModuleNotFoundError: No module named 'hvac_bms'` occurs when only
`app.py` is uploaded, or when the `hvac_bms` directory is not committed at the
same repository level.

## Required repository layout

```text
streamlit_app.py
app.py
requirements.txt
runtime.txt
.streamlit/
  config.toml
hvac_bms/
  __init__.py
  config.py
  controls.py
  faults.py
  io_utils.py
  models.py
  reporting.py
  simulator.py
  validation.py
  weather.py
sample_data/
```

## Deployment procedure

1. Extract the cloud-ready ZIP.
2. Upload **all extracted files and directories** to the root of one GitHub
   repository. Do not upload only `app.py`.
3. In Streamlit Community Cloud, choose that repository and branch.
4. Set **Main file path** to `streamlit_app.py`.
5. Open **Advanced settings** and confirm Python 3.12 if the runtime selector is
   available. The included `runtime.txt` also requests Python 3.12.
6. Deploy or reboot the app.

## Updating an existing failed repository

Delete or replace the old repository contents, then upload the full cloud-ready
bundle. In Streamlit Cloud, open **Manage app → Settings**, set the main file to
`streamlit_app.py`, save, and reboot.
