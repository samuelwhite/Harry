# 🧠 Harry — HARdware Review buddY

Hardware awareness for small infrastructure environments.

Experimental • Home Lab Tool • Quiet Infrastructure

![Release](https://img.shields.io/github/v/release/samuelwhite/Harry)
![Licence](https://img.shields.io/github/license/samuelwhite/Harry)

![Harry Fleet](assets/harry_dashboard.png)
![Harry Nodes](assets/harry_dashboard_2.png)

Harry is a lightweight **hardware awareness layer** for small multi-node environments.

It exists because a thing happened:

> I was no longer managing infrastructure — I was remembering it.

Harry reduces cognitive overload by keeping a fleet **visible, comparable, and contract-validated**.

If it runs quietly for years, we’ve won. **Boring is good.**

---

# 🚀 Quick Start

## 🪟 Windows (Easiest Setup)

Download the latest installer:

https://github.com/samuelwhite/Harry/releases

Run:

HarryBrainSetup.exe

The installer will:

• install Harry Brain  
• install the local Agent  
• configure services  
• open firewall port (8787)  
• start everything automatically  
• open the dashboard  

Then open:

http://localhost:8787

Your machine will automatically register as the first node.

---

## 🐧 Linux Brain (Most Stable)

git clone https://github.com/samuelwhite/Harry.git
cd Harry
./install.sh

After install:

UI:     http://<host>:8787
Health: http://<host>:8787/health

---

## ➕ Add another machine

### From the UI (Recommended)

Use the Downloads page.

It provides:

• pre-configured installers  
• the correct Brain address  
• step-by-step onboarding  

---

### Linux Agent

export HARRY_BASE_URL="http://<brain-host>:8787"

curl -fsSL "$HARRY_BASE_URL/scripts/install-agent.sh" | sudo -E bash

---

### Windows Agent

Run:

HarryAgentSetup.exe

Tip: Use the exact Brain address shown in the UI

---

# 🧠 How Harry Works

Harry consists of two components:

- Brain — central service that collects, stores, and visualises data  
- Agent — lightweight process installed on each machine  

Agents send hardware and health data to the Brain over HTTP.

The Brain provides a UI to:

• view your fleet  
• compare hardware  
• detect issues early  

---

# 🧭 UI Overview

Fleet  
• overview  
• nodes  
• trends  
• hidden nodes  

Inventory  
• summary  
• comparison table  
• node details  

Diagnostics  
• summary  
• recommendations  
• statistics  

Downloads  
• installers  
• Brain address  
• onboarding steps  

---

# 🌐 Networking Notes

Harry Agents must reach the Brain over HTTP.

Default:
Port: 8787

Requirements:

• allow TCP port 8787 through firewall  
• ensure machines can reach the Brain  

Different subnets?

• routing must be enabled  
• firewall rules must allow traffic  

Test connectivity (from the machine you're installing an Agent on):

Test-NetConnection <brain-ip> -Port 8787

---

# ⚠️ Troubleshooting

Agent cannot connect:

• check Brain is running  
• open Brain URL from Agent machine  
• ensure port 8787 is open  

Node not appearing:

• wait ~30 seconds  
• refresh Fleet page  

---

# Architecture

Diagram (Mermaid):

flowchart LR

A[Nodes] --> B[Harry Agent]
B --> C[Harry Brain]

C --> D[Snapshot Store (SQLite)]
C --> E[Advice Engine]
C --> F[Schema Distribution]

C --> G[Fleet Dashboard UI]

---

Brain:

• ingest validated snapshots  
• compute node health  
• store historical data  
• expose UI and APIs  

---

Agent:

Linux:
• bash + embedded Python  
• systemd timer (5 min)  

Windows:
• compiled executable  
• WinSW service  

---

# Useful Endpoints

UI: /
Health: /health
Version: /version
Nodes: /nodes
Doctor: /doctor /doctor.json

Agent:
• /dist/harry_agent.sh
• /scripts/install-agent.sh

---

# Philosophy

Harry exists to reduce cognitive load.

You shouldn’t need to remember your infrastructure.  
You should be able to see it.

If it runs quietly for years — we’ve won.

---

# Status

Linux Agent: Stable  
Windows Agent: Supported  
Linux Brain: Stable  
Windows Brain: Supported  

---

# Security notes

• Agents only push data  
• Brain never SSHs into nodes  
• Use HTTPS if exposed externally  
• No authentication  

Designed for trusted networks / home labs

---

# Closing

If the system fades into the background and just quietly works —
Harry has done its job.
