$ErrorActionPreference = "SilentlyContinue"
$candidates = New-Object System.Collections.Generic.List[string]

function Add-Candidate([string]$path) {
    if ($path -and (Test-Path -LiteralPath $path)) {
        $resolved = (Resolve-Path -LiteralPath $path).Path
        if (-not $candidates.Contains($resolved)) {
            $candidates.Add($resolved)
        }
    }
}

# Comandos expuestos por PATH o por App Execution Aliases.
foreach ($name in @("py.exe", "python.exe", "python3.exe", "python3.13.exe", "python3.12.exe", "python3.11.exe")) {
    $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue
    if ($command) { Add-Candidate $command.Source }
}

# Registro estándar PEP 514 usado por python.org y varios instaladores.
foreach ($root in @(
    "HKCU:\Software\Python\PythonCore",
    "HKLM:\Software\Python\PythonCore",
    "HKLM:\Software\WOW6432Node\Python\PythonCore"
)) {
    foreach ($version in Get-ChildItem $root -ErrorAction SilentlyContinue) {
        $installKey = Join-Path $version.PSPath "InstallPath"
        $props = Get-ItemProperty $installKey -ErrorAction SilentlyContinue
        Add-Candidate $props.ExecutablePath
        $directory = (Get-Item $installKey -ErrorAction SilentlyContinue).GetValue("")
        if ($directory) { Add-Candidate (Join-Path $directory "python.exe") }
    }
}

# Rutas frecuentes de python.org, WindowsApps y Python Install Manager.
$patterns = @(
    "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe",
    "$env:LOCALAPPDATA\Python\pythoncore-*\python.exe",
    "$env:LOCALAPPDATA\Microsoft\WindowsApps\python*.exe",
    "$env:LOCALAPPDATA\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.*\python*.exe",
    "$env:ProgramFiles\Python*\python.exe",
    "${env:ProgramFiles(x86)}\Python*\python.exe",
    "C:\Python*\python.exe"
)
foreach ($pattern in $patterns) {
    foreach ($item in Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue) {
        Add-Candidate $item.FullName
    }
}

# Paquetes instalados desde Microsoft Store.
foreach ($package in Get-AppxPackage -Name "*Python*" -ErrorAction SilentlyContinue) {
    if ($package.InstallLocation) {
        foreach ($item in Get-ChildItem -Path $package.InstallLocation -Filter "python*.exe" -File -Recurse -ErrorAction SilentlyContinue) {
            Add-Candidate $item.FullName
        }
    }
}

# Aceptar únicamente un Python real 3.11 o superior.
foreach ($candidate in $candidates) {
    & $candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        [Console]::Out.WriteLine($candidate)
        exit 0
    }
}

exit 1
