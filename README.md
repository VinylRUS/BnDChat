# BnDChat

Desktop prototype with **legacy BnDChat visual style** and Matrix-ready structure.

## What is included
- PyQt5 UI based on old app look (dark card layout, orange accents, side panel + chat panel)
- Matrix service adapter class (`MatrixService`) to plug into Matrix API client
- Demo mode out of the box so UI can be tested instantly

## Run
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install PyQt5
python bndchat_matrix_pyqt.py
```

## Matrix integration plan
`MatrixService` is intentionally isolated so we can next connect `matrix-nio` (or another Matrix SDK) without changing UI widgets.
