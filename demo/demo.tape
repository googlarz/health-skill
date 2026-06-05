Output demo/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 780
Set Height 420
Set Theme "Catppuccin Mocha"
Set Padding 20
Set TypingSpeed 55ms
Set PlaybackSpeed 1

Hide
Type `export HEALTH_ROOT=/tmp/health-demo`
Enter
Type `cd /Users/dawid/Claude\ Code/Dev/health-skill`
Enter
Sleep 300ms
Show

Type `python3 -m scripts.commands hi`
Enter
Sleep 2500ms

Enter
Sleep 600ms

Type `python3 -m scripts.commands status`
Enter
Sleep 2500ms

Enter
Sleep 600ms

Type `python3 -m scripts.commands explain-lab --marker LDL --value 162`
Enter
Sleep 3000ms

Sleep 2s
