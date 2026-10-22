import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNATURE_DIR = os.path.join(BASE_DIR, "static", "signatures")
DEFAULT_DEPARTMENT = "MCA"

DEPARTMENTS = {
    "MCA": {
        "name": "MCA",
        "hod_name": "Dr Bruce Mathew",
        "hod_title": "Head- MCA",
        "hod_signature": "MCA_hod.png",
        "coordinator_name": "Mr Ragesh Raju",
        "coordinator_title": "Program Coordinator",
        "coordinator_signature": "MCA_coordinator.png",
    },
    "CSE": {
        "name": "Computer Science & Engineering",
        "hod_name": "Dr <CSE HOD name>",
        "hod_title": "Head- CSE",
        "hod_signature": "CSE_hod.png",
        "coordinator_name": "<CSE coordinator name>",
        "coordinator_title": "Program Coordinator",
        "coordinator_signature": "CSE_coordinator.png",
    },
    "ISE": {
        "name": "Information Science & Engineering",
        "hod_name": "Dr <ISE HOD name>",
        "hod_title": "Head- ISE",
        "hod_signature": "ISE_hod.png",
        "coordinator_name": "<ISE coordinator name>",
        "coordinator_title": "Program Coordinator",
        "coordinator_signature": "ISE_coordinator.png",
    },
    "ECE": {
        "name": "Electronics & Communication Engineering",
        "hod_name": "Dr <ECE HOD name>",
        "hod_title": "Head- ECE",
        "hod_signature": "ECE_hod.png",
        "coordinator_name": "<ECE coordinator name>",
        "coordinator_title": "Program Coordinator",
        "coordinator_signature": "ECE_coordinator.png",
    },
    "ME": {
        "name": "Mechanical Engineering",
        "hod_name": "Dr <ME HOD name>",
        "hod_title": "Head- ME",
        "hod_signature": "ME_hod.png",
        "coordinator_name": "<ME coordinator name>",
        "coordinator_title": "Program Coordinator",
        "coordinator_signature": "ME_coordinator.png",
    },
    "CV": {
        "name": "Civil Engineering",
        "hod_name": "Dr <CV HOD name>",
        "hod_title": "Head- CV",
        "hod_signature": "CV_hod.png",
        "coordinator_name": "<CV coordinator name>",
        "coordinator_title": "Program Coordinator",
        "coordinator_signature": "CV_coordinator.png",
    },
}


def resolve(event_department=None, organizer_department=None):
    for raw in (event_department, organizer_department):
        key = (raw or "").strip().upper()
        if not key:
            continue
        if key in DEPARTMENTS:
            return key, DEPARTMENTS[key]
        for code, info in DEPARTMENTS.items():
            if info["name"].upper() == key:
                return code, info
    return DEFAULT_DEPARTMENT, DEPARTMENTS[DEFAULT_DEPARTMENT]


def signature_path(filename):
    if not filename:
        return None
    path = os.path.join(SIGNATURE_DIR, filename)
    return path if os.path.exists(path) else None