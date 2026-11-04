param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
$taskRunner = Join-Path $PSScriptRoot 'run-task.ps1'
$taskAccount = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskAccount -LogonType Interactive -RunLevel Limited
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 4)
foreach ($taskMode in @('collect','daily')) {
    $taskName = if ($taskMode -eq 'collect') { 'AstroBriefVi-Collect' } else { 'AstroBriefVi-Daily' }
    $taskArguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $taskRunner + '" -Mode ' + $taskMode
    $taskAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $taskArguments -WorkingDirectory $taskProjectRoot
    # Windows prepares stock all day; the cloud publisher enforces 07:00 and the daily cap.
    $taskMinute = if ($taskMode -eq 'daily') { 0 } else { 5 }
    $taskTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date -Hour 0 -Minute $taskMinute -Second 0) -RepetitionInterval (New-TimeSpan -Hours 1)
    $taskVietnamDate = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTimeOffset]::UtcNow, 'SE Asia Standard Time').ToString('yyyy-MM-dd')
    $taskTrigger.StartBoundary = $taskVietnamDate + ('T00:{0:00}:00+07:00' -f $taskMinute)
    $taskLogonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $taskAccount
    $taskDefinition = New-ScheduledTask -Action $taskAction -Trigger @($taskTrigger,$taskLogonTrigger) -Settings $taskSettings -Principal $taskPrincipal -Description 'AstroBrief Viet v2: prepare reviewed stock locally; GitHub publishes up to five verified articles per Vietnam day.'
    if ($DryRun) {
        [pscustomobject]@{TaskName=$taskName;Account=$taskAccount;Mode=$taskMode;Root=$taskProjectRoot;TaskXml=(Export-ScheduledTask -InputObject $taskDefinition)} | ConvertTo-Json -Depth 4
    } else {
        Register-ScheduledTask -TaskName $taskName -InputObject $taskDefinition -Force | Select-Object TaskName,State
    }
}
