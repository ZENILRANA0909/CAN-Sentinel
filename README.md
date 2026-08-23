# CAN-Sentinel

## Automotive ECU Intrusion Detection System

CAN-Sentinel is an automotive cybersecurity capstone project that simulates an automotive Controller Area Network (CAN), multiple Electronic Control Units (ECUs), CAN traffic monitoring, and security analysis.

The system is being developed as an internship capstone project with a modular architecture designed for real-time CAN intrusion detection using machine learning.

---

## Project Status

### Implemented

- [x] Project structure
- [x] Python configuration
- [x] CAN message model
- [x] CAN ID validation
- [x] CAN data validation
- [x] python-can integration
- [x] Virtual CAN support
- [x] Shared CAN interface
- [x] Engine ECU
- [x] Brake ECU
- [x] Speed ECU
- [x] Steering ECU
- [x] Door ECU
- [x] ECU Manager
- [x] Multi-threaded ECU simulation
- [x] CAN Receiver
- [x] Real-time CAN frame callback
- [x] CAN traffic CSV logger
- [x] Timestamp logging
- [x] CAN ID logging
- [x] DLC logging
- [x] CAN data logging
- [x] Attack-label field
- [x] Logging tests
- [x] CAN receiver tests
- [x] CAN message tests
- [x] 8 automated tests
- [x] GitHub repository
- [x] GitHub Actions CI
- [x] Python bytecode/cache protection through `.gitignore`

### In Development

- [ ] Automatic Receiver → Logger integration
- [ ] Real-time CAN traffic monitor
- [ ] Attack simulation framework
- [ ] Fake Speed attack
- [ ] Fake Brake attack
- [ ] Flood attack
- [ ] Replay attack
- [ ] ECU ID spoofing
- [ ] Random CAN injection
- [ ] Bus saturation attack
- [ ] Attack detection
- [ ] Dataset generation
- [ ] Feature engineering
- [ ] Isolation Forest model
- [ ] Real-time ML prediction
- [ ] Prediction confidence
- [ ] SQLite database
- [ ] PyQt6 dashboard
- [ ] Matplotlib visualization
- [ ] Alert history
- [ ] CSV/JSON export
- [ ] PDF security report
- [ ] Stress testing
- [ ] Complete documentation

---

# System Architecture

```text
                         CAN-Sentinel
                              |
                              v
                        ECU Manager
                              |
                              v
                     Shared CAN Interface
                              |
                              v
                       Virtual CAN Bus
                              |
          +-------------------+-------------------+
          |                   |                   |
          v                   v                   v
      Engine ECU          Brake ECU          Speed ECU
       ID 0x100            ID 0x200            ID 0x300
          |                   |                   |
          +-------------------+-------------------+
                              |
                    +---------+---------+
                    |                   |
                    v                   v
              Steering ECU          Door ECU
               ID 0x400             ID 0x500
                              |
                              v
                        CAN Receiver
                              |
                              v
                         CAN Logger
                              |
                              v
                         CSV Dataset
                              |
                              v
                    Machine Learning
                              |
                              v
                     Intrusion Detection
                              |
                              v
                         Dashboard
