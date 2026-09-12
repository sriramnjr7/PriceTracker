' SriTrack Silent 24/7 Radar Daemon Launcher
' Launches run_247_radar.py completely in the background without any visible command prompt window.
' Logs are written to radar_daemon.log in the project folder.

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

strScriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
If Not fso.FileExists(strScriptDir & "\run_247_radar.py") Then
    MsgBox "Error: run_247_radar.py was not found in the script directory!", 16, "SriTrack Daemon Error"
    WScript.Quit 1
End If

WshShell.CurrentDirectory = strScriptDir

' Run python in completely hidden window (0 = hidden, False = don't wait for completion)
WshShell.Run "cmd /c py -3 run_247_radar.py >> radar_daemon.log 2>&1", 0, False

MsgBox "SriTrack 24/7 Radar Daemon has started in the background!" & vbCrLf & vbCrLf & _
       "- Sweeps Casio deals every 90 seconds" & vbCrLf & _
       "- Sweeps tracked items every 120 seconds" & vbCrLf & _
       "- Live logs saved to radar_daemon.log" & vbCrLf & vbCrLf & _
       "To stop anytime, run stop_radar_daemon.cmd", 64, "SriTrack Daemon Online"
