# CAN-Sentinel

CAN-Sentinel is a Python-based automotive cybersecurity monitoring project designed to simulate a vehicle Controller Area Network (CAN), monitor CAN traffic, log messages, and detect simulated CAN attacks.

The project is being developed as a modular security-monitoring platform for learning and demonstrating automotive cybersecurity concepts.

---

## Project Objectives

CAN-Sentinel aims to:

- Simulate multiple vehicle Electronic Control Units (ECUs)
- Establish communication through a shared virtual CAN bus
- Receive and monitor CAN frames
- Validate CAN message IDs and payloads
- Log CAN traffic into CSV files
- Simulate controlled CAN attacks
- Detect suspicious CAN traffic
- Classify detected attacks
- Provide automated tests for the system components

---

## Current Architecture

```text
                    CAN-Sentinel
                         |
                +--------+--------+
                |                 |
          ECU Simulation      Attack Simulation
                |                 |
        +-------+-------+    Fake Speed Attack
        |       |       |
      Engine  Brake   Speed
        ECU     ECU     ECU
        |       |       |
        +-------+-------+
                |
          Steering ECU
                |
            Door ECU
                |
                v
          Virtual CAN Bus
                |
                v
          CAN Receiver
                |
                v
        Traffic Monitor
                |
        +-------+-------+
        |               |
   Attack Detection   Normal Traffic
        |
        v
     CAN Logger
        |
        v
     CSV Dataset
