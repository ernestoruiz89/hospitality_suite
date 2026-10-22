<# Start the existing named WSL test bench after a Windows/WSL restart. #>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$hotelRepoWindows = Split-Path -Parent $PSScriptRoot
$hotelRepoWslOutput = & wsl.exe -d Ubuntu-24.04 -u frappe --exec /usr/bin/wslpath -a -u $hotelRepoWindows.Replace('\', '/')
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($hotelRepoWslOutput)) {
    throw 'No se pudo localizar este repositorio dentro de Ubuntu-24.04.'
}
$hotelRepoWsl = $hotelRepoWslOutput.Trim()
if (-not $hotelRepoWsl.StartsWith('/')) { throw 'La ruta WSL del repositorio no es absoluta.' }

& wsl.exe -d Ubuntu-24.04 -u root --exec /usr/bin/python3 "$hotelRepoWsl/tools/configure_local_hosts.py"
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron verificar los alias locales del sitio de pruebas.' }

& wsl.exe -d Ubuntu-24.04 -u frappe --cd /home/frappe/benches/hospitality-bench --exec env/bin/python "$hotelRepoWsl/tools/run_dev.py"
if ($LASTEXITCODE -ne 0) { throw 'No se pudo iniciar el bench de pruebas. Revise el mensaje anterior.' }

$hotelSiteUrl = 'http://hospitality.localhost:8086'
& wsl.exe -d Ubuntu-24.04 -u frappe --cd /home/frappe/benches/hospitality-bench --exec env/bin/python "$hotelRepoWsl/tools/check_local_hotel.py"
if ($LASTEXITCODE -ne 0) { throw 'El sitio todavía no respondió. Revise .hospitality-run del bench.' }
Write-Output "Hotel disponible: $hotelSiteUrl/desk/hospitality-suite/hospitality-reservations"
