After changing dependencies:

```
python -m pip install pip-tools
pip-compile --generate-hashes --upgrade ./requirements.in
```

Optional:

```
nox --session setup (to bundle libs in local dev)
```
