Harry Windows Agent

This folder contains the Windows agent for the Harry infrastructure monitoring system.


Files included

install_agent.ps1
PowerShell installer for the agent.

uninstall_agent.ps1
Removes the agent and Windows service.

harry_agent.exe
Compiled Harry agent runtime.

HarryAgentService.exe
Windows Service Wrapper (WinSW).

HarryAgentService.xml
Service configuration.

START-HERE.txt
Quick installation instructions.

agent_config.sample.json
Example configuration file.


Quick Start

1. Extract the ZIP archive.

2. Open PowerShell as Administrator.

3. Change into the extracted folder.

4. Run the installer:

   .\install_agent.ps1

5. Enter the Harry Brain address when prompted.


Example Brain URL

http://192.168.1.20:8787


Installation Result

The installer will:

• Copy files to:
  C:\ProgramData\Harry

• Create configuration file:
  agent_config.json

• Install the Windows service:
  HarryAgentService

• Start the agent automatically.


Logs

Log files are written to:

C:\ProgramData\Harry

Important logs:

HarryAgentService.wrapper.log
HarryAgentService.out.log
HarryAgentService.err.log


Viewing logs

To watch the agent log live in PowerShell:

Get-Content "C:\ProgramData\Harry\HarryAgentService.out.log" -Wait


Project

Harry — HARdware Review buddY

Hardware awareness for small infrastructure environments.

GitHub:
https://github.com/samuelwhite/Harry
