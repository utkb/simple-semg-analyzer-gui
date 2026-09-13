# Installation Guide (No Programming Experience Required)

This guide walks you through installing and running **Simple sEMG Analyzer GUI**
step by step, assuming you have never used Python or a command line before. It
is written for researchers and clinicians who understand EMG but not
software development — no prior coding knowledge is assumed.

There is no installer for this program (see the note at the end for why).
Instead, you will install Python once, download the project's code, and run
it directly. This takes about 15–20 minutes the first time.

---

## What you will need

- A Linux, Windows, or macOS computer
- An internet connection (only needed for installation, not for daily use —
  the program works fully offline once installed)
- About 200 MB of free disk space

---

## Step 1 — Install Python

The program is written in Python, a programming language. You need Python
installed on your computer before anything else will work.

### Linux (Ubuntu/Kubuntu/Debian-based)

Most Linux distributions already include Python. Open a terminal and run:
```
sudo apt update
sudo apt install python3 python3-venv python3-pip python3-tk
```
The `python3-tk` package is important — it provides the GUI toolkit the
program is built on, and Linux does not always install it by default.

### Windows

1. Go to [python.org/downloads](https://www.python.org/downloads/) and
   download the latest Python 3 installer (3.10 or newer).
2. Run the installer. **Important:** on the first screen, check the box
   that says **"Add python.exe to PATH"** before clicking Install. This step
   is easy to miss and causes most installation problems if skipped.
3. Once installation finishes, open the **Start Menu**, type `cmd`, and open
   **Command Prompt**. Type the following and press **Enter**:
   ```
   python --version
   ```
   You should see something like `Python 3.11.x`. If you instead see an
   error, restart your computer and try again — the PATH setting sometimes
   needs a restart to take effect.

### macOS

1. Go to [python.org/downloads](https://www.python.org/downloads/) and
   download the latest Python 3 installer (3.10 or newer) for macOS.
2. Run the installer, following the on-screen instructions (default options
   are fine).
3. Open **Terminal** (search for it with Spotlight, ⌘+Space, then type
   "Terminal"). Type the following and press **Enter**:
   ```
   python3 --version
   ```
   You should see something like `Python 3.11.x`.

---

## Step 2 — Download the project code

The project's code is hosted on GitHub (using Git), but you do not need to
know Git for this — a plain download works fine.

1. Go to the project's GitHub page (the repository named
   `simple-semg-analyser-gui`).
2. Click the green **"Code"** button, then **"Download ZIP"**.
3. Extract the ZIP file somewhere easy to find, e.g. your Desktop or
   Documents folder. You should end up with a folder containing files like
   `gui.py`, `flagging.py`, `pipeline.py`, and a `protocols/` folder.

*(If you are comfortable with Git, `git clone <repository-url>` works the
same way and makes future updates easier — but it is not required.)*

---

## Step 3 — Open a terminal in the project folder

- **Linux:** right-click inside the extracted folder in your file manager
  and choose "Open Terminal Here" (exact wording varies by desktop
  environment), or use `cd` the same way as macOS.
- **Windows:** open the extracted folder in File Explorer, then click on
  the address bar, type `cmd`, and press Enter. This opens a Command
  Prompt already pointed at that folder.
- **macOS:** open Terminal, type `cd ` (with a trailing space), then drag
  the extracted folder into the Terminal window — it will fill in the
  path automatically. Press Enter.

---

## Step 4 — Create a virtual environment

A virtual environment keeps this project's dependencies separate from
anything else on your computer, so nothing conflicts. Run:

**Windows:**
```
python -m venv venv
venv\Scripts\activate
```

**macOS/Linux:**
```
python3 -m venv venv
source venv/bin/activate
```

After activation, your terminal prompt should show `(venv)` at the start
of the line. You will need to run the activation command again each time
you open a new terminal to use the program — but you only create the
environment once.

---

## Step 5 — Install the required libraries

With the virtual environment active, run:
```
pip install -r requirements.txt
```
This downloads and installs everything the program needs (NumPy, SciPy,
Matplotlib, and CustomTkinter). It may take a few minutes.

If there is no `requirements.txt` file in the folder, install the
libraries directly instead:
```
pip install numpy scipy matplotlib customtkinter
```

---

## Step 6 — Run the program

With the virtual environment still active, run:
```
python gui.py
```
(on macOS/Linux you may need `python3 gui.py` instead, depending on your
system).

The main pipeline window should open. From here you can load a recording
and step through the processing pipeline (DC offset removal, filtering,
rectification, and so on).

For region flagging and feature extraction, run instead:
```
python flagging.py your_recording.csv
```

---

## Every time after the first install

You do not need to repeat Steps 1–5 again. Each new session, just:

1. Open a terminal in the project folder (Step 3).
2. Activate the virtual environment (Step 4's second command only).
3. Run `python gui.py`.

---

## How to update

This project is under active development, so newer versions with bug
fixes and features are released regularly. Neither method below touches
your virtual environment or your recorded data — only the program's own
files change.

**If you downloaded a ZIP (Step 2):**

1. Go back to the project's GitHub page and download the ZIP again, the
   same way as in Step 2.
2. Extract it, and copy the new `.py` files and the `protocols/` folder
   into your existing project folder, overwriting the old ones. Your
   `venv` folder (and any recordings you keep in the same folder) will
   be left untouched, since the new ZIP doesn't contain them.
3. If `requirements.txt` changed (check whether its content looks
   different from before), repeat Step 5 to install any new
   dependencies. Otherwise you can skip straight to Step 6.

**If you used `git clone`:** open a terminal in the project folder and
run:
```
git pull
```
then repeat Step 5 if `requirements.txt` changed.

---

## Troubleshooting

| Problem | Likely fix |
|---|---|
| `'python' is not recognized...` (Windows) | Python wasn't added to PATH during install. Reinstall Python and make sure to check "Add python.exe to PATH". |
| `ModuleNotFoundError: No module named 'customtkinter'` (or similar) | The virtual environment isn't activated, or Step 5 wasn't run. Repeat Step 4's activation command, then Step 5. |
| `ModuleNotFoundError: No module named 'tkinter'` (Linux) | Run `sudo apt install python3-tk` and try again. |
| The window opens but looks broken or tiny | Try resizing the window manually; this is a known cosmetic issue on some display scaling settings. |
| Nothing happens when you double-click `gui.py` | This program must be run from a terminal, not by double-clicking the file — see Step 6. |

If none of these resolve your issue, note the exact error message shown in
the terminal and reach out for help — the full error text is almost always
needed to diagnose the problem.

---

## Why is there no simple installer (.exe / .dmg)?

This is a research and teaching tool built and maintained by one developer
for a specific line of research, not a commercial product. Building and
maintaining installers for every platform is a substantial ongoing burden
that isn't proportional to the tool's audience size. A clear step-by-step
guide, run from source, was chosen instead as the sustainable option.
