# Contributing to CYD Deck

Thanks for wanting to help. This is a small hobby project so the bar is low — just follow the guidelines below and you're good.

---

## Ways to contribute

- **Bug reports** — open a GitHub issue. Include what you did, what happened, and what you expected. A serial log helps for firmware bugs.
- **Bug fixes** — fork the repo, fix it, open a pull request. Keep the PR focused on one thing.
- **New button types** — add the type to `TYPES` in the editor and implement the matching case in `executeButton()` in the firmware.
- **New key mappings** — all punctuation lives in `punctKey()` in `CYDDeck.ino`. Add the case there and it works in both `typeText()` and `sendSingleShortcut()` automatically.
- **Documentation** — typos, unclear steps, missing troubleshooting entries — all welcome.

---

## Ground rules

- Test on real hardware before opening a PR if you can. The CYD is cheap and widely available.
- Keep changes small and focused. One fix or feature per PR makes review easier.
- Match the existing code style — the firmware uses compact one-liners for short functions, the editor uses PEP 8 formatting.
- Don't add new Python dependencies to the editor without a good reason. The current install is one `pip` command and that's worth keeping.
- Don't break existing `.deck` files — the JSON format is the public interface between the editor and the firmware.

---

## Setting up

**Firmware**
1. Follow the setup steps in the main README — install the libraries, copy `User_Setup_Select.h`, flash the board.
2. Open the Serial Monitor at 115200 baud to see debug output while developing.

**Editor**
```bash
py -m pip install customtkinter tkinterdnd2
py CYDDeckEditor.py
```

No build step needed. Edit and run.

---

## Submitting a pull request

1. Fork the repo and create a branch from `main`.
2. Make your changes.
3. Test them — on device for firmware changes, by running the editor for Python changes.
4. Open a PR with a short description of what changed and why.

---

## Contributors

If you contribute a fix or feature, add your name here.

| Name | Contribution |
|---|---|
| cam2135 | Original project |
