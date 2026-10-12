# ESP32 CAM Port Checker Script
Write-Host "=== ESP32 CAM Port Detection ===" -ForegroundColor Green

Write-Host "`nChecking for Serial Ports..." -ForegroundColor Yellow
$serialPorts = Get-WmiObject -Class Win32_SerialPort | Select-Object DeviceID, Description, Status
if ($serialPorts) {
    $serialPorts | Format-Table -AutoSize
} else {
    Write-Host "No serial ports found!" -ForegroundColor Red
}

Write-Host "`nChecking for USB-to-Serial Devices..." -ForegroundColor Yellow
$usbSerial = Get-PnpDevice | Where-Object {
    $_.FriendlyName -like "*CH340*" -or 
    $_.FriendlyName -like "*CH9102*" -or 
    $_.FriendlyName -like "*CP210*" -or 
    $_.FriendlyName -like "*FTDI*" -or
    $_.FriendlyName -like "*Serial*"
} | Select-Object FriendlyName, Status, Class

if ($usbSerial) {
    $usbSerial | Format-Table -AutoSize
} else {
    Write-Host "No USB-to-Serial devices found!" -ForegroundColor Red
}

Write-Host "`nAvailable COM Ports:" -ForegroundColor Yellow
$comPorts = [System.IO.Ports.SerialPort]::GetPortNames()
if ($comPorts) {
    $comPorts | ForEach-Object { Write-Host "  $_" -ForegroundColor Cyan }
} else {
    Write-Host "No COM ports available!" -ForegroundColor Red
}

Write-Host "`n=== Instructions ===" -ForegroundColor Green
Write-Host "1. If you see COM ports above, use them in Arduino IDE"
Write-Host "2. If status shows 'Unknown' or 'Error', reinstall drivers"
Write-Host "3. Make sure ESP32 CAM is connected and in programming mode (IO0 to GND)"
