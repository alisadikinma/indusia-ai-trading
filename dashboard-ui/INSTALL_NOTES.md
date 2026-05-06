# Node 22+ install — per platform

The Bot Cockpit requires Node 22+ (24 recommended). The deploy target VPS is
Hetzner CX22 (Ubuntu 24.04). Operator dev machines are Windows 11.

## Windows 11 (operator dev box)

### Option A — winget (preferred)
```powershell
winget install OpenJS.NodeJS.LTS
node --version   # expect v22.x or higher
```

### Option B — Chocolatey
```powershell
choco install nodejs-lts -y
node --version
```

### Option C — nvm-windows (recommended for multi-version)
```powershell
winget install CoreyButler.NVMforWindows
nvm install 22
nvm use 22
node --version
```

## Ubuntu 24.04 (Hetzner VPS)

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs build-essential
node --version
```

`build-essential` is required so `argon2` (native node-gyp build) compiles on
first `npm install`.

## macOS (any operator with a Mac)

```bash
brew install node@22
brew link node@22 --force
node --version
```

## Verifying the install

```bash
node --version    # >= 22.0.0
npm  --version    # >= 10
```

Then run `npm install` inside `dashboard-ui/`. If the argon2 native build
fails on Windows, install the VS Build Tools workload "Desktop development
with C++" via the Visual Studio Installer and retry.
