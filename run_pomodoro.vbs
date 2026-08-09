Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
launcher = scriptDir & "\run_pomodoro.pyw"

On Error Resume Next
shell.Run "py -3w """ & launcher & """", 0, False
If Err.Number <> 0 Then
    Err.Clear
    shell.Run "pythonw.exe """ & launcher & """", 0, False
End If
