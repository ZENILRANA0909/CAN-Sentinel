# CAN-Sentinel

## Automotive ECU Intrusion Detection System

CAN-Sentinel is an automotive cybersecurity project designed to simulate a vehicle CAN network, generate ECU traffic, and provide a foundation for real-time intrusion detection.

The project is being developed as an internship capstone project using Python and `python-can`, with a modular architecture designed to support attack simulation, machine learning-based detection, logging, and a professional PyQt6 dashboard.

---

## Project Status

### Currently Implemented

* [x] Project structure
* [x] Python configuration
* [x] CAN message model
* [x] CAN message validation
* [x] CAN interface
* [x] Virtual CAN bus support
* [x] Engine ECU simulation
* [x] Brake ECU simulation
* [x] Speed ECU simulation
* [x] Steering ECU simulation
* [x] Door ECU simulation
* [x] ECU manager
* [x] Shared CAN interface architecture
* [x] Logging configuration
* [x] Initial unit tests
* [x] GitHub repository
* [x] GitHub Actions CI

### Planned

* [ ] CAN traffic receiver
* [ ] CAN packet logger
* [ ] CSV logging
* [ ] SQLite database
* [ ] Attack simulator
* [ ] Flood attack
* [ ] Replay attack
* [ ] Fake speed attack
* [ ] Fake brake attack
* [ ] ECU spoofing
* [ ] Random injection
* [ ] Bus saturation
* [ ] Dataset generation
* [ ] Isolation Forest model
* [ ] Real-time ML prediction
* [ ] PyQt6 dashboard
* [ ] Real-time Matplotlib charts
* [ ] Alert history
* [ ] CSV/JSON export
* [ ] PDF reporting
* [ ] Stress testing
* [ ] Complete documentation

---

# Architecture

The current CAN simulation architecture uses a single shared CAN interface.

```text
                    CAN-Sentinel
                         |
                    ECU Manager
                         |
                  Shared CAN Bus
                         |
        +----------------+----------------+
        |                |                |
   Engine ECU        Brake ECU        Speed ECU
     0x100             0x200             0x300
        |                |                |
        +----------------+----------------+
                         |
                  Steering ECU
                     0x400
                         |
                     Door ECU
                     0x500
```

The architecture is designed so that the CAN receiver, logger, attack simulator, machine learning detector, and dashboard can later consume the same CAN traffic.

---

# ECU Configuration

| ECU          |  CAN ID | Main Data           |
| ------------ | ------: | ------------------- |
| Engine ECU   | `0x100` | RPM, vehicle speed  |
| Brake ECU    | `0x200` | Brake pressure, ABS |
| Speed ECU    | `0x300` | Vehicle speed       |
| Steering ECU | `0x400` | Steering angle      |
| Door ECU     | `0x500` | Door status         |

---

# Technology Stack

* Python 3.12+
* python-can
* PyQt6
* NumPy
* Pandas
* Scikit-learn
* Matplotlib
* SQLite
* pytest
* Git
* GitHub Actions

---

# Project Structure

```text
CAN-Sentinel/
│
├── main.py
├── requirements.txt
├── README.md
├── LICENSE
├── .gitignore
│
├── config/
│   ├── __init__.py
│   ├── settings.py
│   └── logging_config.py
│
├── src/
│   ├── __init__.py
│   │
│   ├── networking/
│   │   ├── __init__.py
│   │   ├── can_interface.py
│   │   ├── can_message.py
│   │   └── can_validator.py
│   │
│   ├── simulation/
│   │   ├── __init__.py
│   │   ├── base_ecu.py
│   │   ├── engine_ecu.py
│   │   ├── brake_ecu.py
│   │   ├── speed_ecu.py
│   │   ├── steering_ecu.py
│   │   ├── door_ecu.py
│   │   └── ecu_manager.py
│   │
│   ├── attacks/
│   ├── ml/
│   ├── dashboard/
│   ├── database/
│   ├── logging/
│   ├── visualization/
│   └── utils/
│
├── datasets/
├── models/
├── logs/
├── reports/
├── exports/
├── docs/
├── tests/
├── scripts/
│
└── .github/
    └── workflows/
        └── python.yml
```

---

# Installation

## 1. Clone the repository

```bash
git clone https://github.com/ZENILRANA0909/CAN-Sentinel.git
```

Enter the project:

```bash
cd CAN-Sentinel
```

---

## 2. Create a virtual environment

### macOS/Linux

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

### Windows

```powershell
python -m venv .venv
```

```powershell
.venv\Scripts\activate
```

---

## 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

---

# Running the Project

Start CAN-Sentinel:

```bash
python main.py
```

The application currently starts the simulated vehicle ECUs.

Expected output includes messages similar to:

```text
===== CAN-Sentinel =====

Starting vehicle simulation...

CAN Interface Initialized

Engine ECU -> ID=0x100 DATA=[...]
Brake ECU -> ID=0x200 DATA=[...]
Speed ECU -> ID=0x300 DATA=[...]
Steering ECU -> ID=0x400 DATA=[...]
Door ECU -> ID=0x500 DATA=[...]
```

Stop the simulator using:

```text
Ctrl + C
```

---

# macOS Development

CAN-Sentinel supports development on macOS using the `python-can` virtual bus backend.

The current configuration uses:

```python
CAN_INTERFACE = "virtual"
CAN_CHANNEL = None
```

This allows the CAN simulation to run without installing Ubuntu or configuring a Linux CAN interface.

---

# Linux SocketCAN

For Linux-based SocketCAN testing, the configuration can use:

```python
CAN_INTERFACE = "socketcan"
CAN_CHANNEL = "vcan0"
```

A Linux virtual CAN interface can be created with:

```bash
sudo modprobe vcan
```

```bash
sudo ip link add dev vcan0 type vcan
```

```bash
sudo ip link set up vcan0
```

The CAN interface can then be inspected using:

```bash
ip link show vcan0
```

---

# Testing

Run the complete test suite:

```bash
python -m pytest
```

Run tests with detailed output:

```bash
python -m pytest -v
```

Compile the source tree:

```bash
python -m compileall src config tests main.py
```

---

# Continuous Integration

CAN-Sentinel uses GitHub Actions to automatically:

1. Check out the repository
2. Install Python
3. Install dependencies
4. Verify pytest
5. Compile Python source files
6. Run automated tests

Workflow:

```text
.github/workflows/python.yml
```

---

# Security Goals

The final system is designed to detect abnormal CAN traffic including:

* Flooding
* Replay attacks
* ECU ID spoofing
* Random CAN injection
* Fake speed messages
* Fake brake messages
* Bus saturation

Machine learning will later be used to identify anomalous CAN traffic using Isolation Forest.

---

# Machine Learning Architecture

The planned detection pipeline is:

```text
CAN Packet
    |
    v
Feature Extraction
    |
    v
Preprocessing
    |
    v
Isolation Forest
    |
    v
Anomaly Score
    |
    v
Prediction
    |
    +---- Normal
    |
    +---- Suspicious
    |
    +---- Attack
```

---

# Planned Dashboard

The final PyQt6 dashboard will provide:

* Live CAN packet table
* Packet rate
* Normal packet counter
* Attack counter
* Current attack
* Prediction confidence
* Attack history
* CAN traffic charts
* Attack timeline
* CPU usage
* Memory usage
* System status
* Attack controls
* Log export
* Settings
* Theme switching

---

# Development Principles

CAN-Sentinel follows these development principles:

* Object-Oriented Programming
* SOLID principles
* Type hints
* Docstrings
* Exception handling
* Input validation
* Modular architecture
* Logging
* Unit testing
* Integration testing
* Secure coding practices
* Separation of responsibilities

---

# Development Roadmap

```text
Phase 1   Project Foundation          [Completed]
Phase 2   CAN Message Model           [Completed]
Phase 3   Utility Layer               [Completed]
Phase 4   ECU Simulation              [In Progress]
Phase 5   CAN Receiver                [Planned]
Phase 6   Data Logger                 [Planned]
Phase 7   Attack Simulator             [Planned]
Phase 8   Dataset Generation           [Planned]
Phase 9   Machine Learning             [Planned]
Phase 10  Real-Time Detection          [Planned]
Phase 11  PyQt6 Dashboard              [Planned]
Phase 12  Database                     [Planned]
Phase 13  Reports                      [Planned]
Phase 14  Testing                      [Planned]
Phase 15  Documentation                [Planned]
```

---

# Disclaimer

CAN-Sentinel is an educational and research project intended for authorized automotive cybersecurity testing and simulation.

Only use CAN-Sentinel on vehicles, test benches, virtual CAN networks, and systems for which you have explicit authorization.

---

# Author

**Zenil Rana**

Automotive Cybersecurity / Software Engineering Capstone Project

---

# License

This project is released under the MIT License.
# CAN-Sentinel
