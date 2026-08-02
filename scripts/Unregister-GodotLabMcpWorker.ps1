[CmdletBinding()]
param(
    [string]$TaskName = "EVAVO Godot Game Test Lab MCP"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[godot-lab] Unregistered '$TaskName'."
}
else {
    Write-Host "[godot-lab] Scheduled task '$TaskName' is not registered."
}
