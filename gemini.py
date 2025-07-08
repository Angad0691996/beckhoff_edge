#All three read included except for write_to_plc nodes and send_to_azure_iot_hub nodes
import pyads
from azure.iot.device import IoTHubDeviceClient, Message
import json
from datetime import datetime
import time
import threading
import signal
from threading import Lock # Ensure Lock is imported
import queue
import re
import traceback # Import traceback for detailed error logging

custom_c = None
stop_thread = threading.Event()
last_processed_message_ids = set()
MAX_MESSAGE_ID_HISTORY = 1000
# Global queue to hold incoming requests
request_queue = queue.Queue()

# >>> Define a single, global lock for ALL PLC access <<<
plc_access_lock = Lock()

# Remove client_lock1 = Lock() and client_lock2 = Lock() if they are still present globally.

def get_current_date_time():
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M:%S")
    return current_date, current_time

# TwinCAT ADS connection parameters
AMS_NET_ID = '5.51.197.248.1.1'  # Your PLC's AMS Net ID
ADS_PORT = 801  # Standard ADS port
# Your PLC's IP address (needed for pyads.Connection if not inferrable)
# Based on your minimal script, you are passing PLC_IP, so let's keep it consistent.
PLC_IP = '192.168.1.1' # <--- CONFIRM THIS IS YOUR PLC'S ACTUAL IP

CONNECTION_STRING= "HostName=CarParking-T1.azure-devices.net;DeviceId=beckhoff-D1;SharedAccessKey=0nUlWgT2ySqehrqVvz1dOfknDiqRcfa3LAIoTHnohFQ="  

#Nodes to read from the PLC Parking site configuration and queue status updates
try:
    with open('nodes.txt', 'r') as file:
        PYADS_VARIABLES = json.load(file)
except Exception as e:
    print(f" Error loading pyads nodes: {e}")
    PYADS_VARIABLES = []

#Nodes to write to the PLC - Hardcoded
WRITE_NODES = [
    {"name": ".Server_To_PLC.Request_Data.Token_No", "type": "PLCTYPE_INT"},
    {"name": ".Server_To_PLC.Request_Data.Car_Type", "type": "PLCTYPE_BYTE"},
    {"name": ".Server_To_PLC.Request_Data.Request_Type", "type": "PLCTYPE_BYTE"},
    {"name": ".Server_To_PLC.Add_Request", "type": "PLCTYPE_BOOL"}    
]

def read_node_ids(file_path):
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading node IDs from file: {e}")
        return {}

def get_non_zero_values(client, node_ids):
    # This function seems to be for OPC UA client (client.get_node), not pyads.
    # If you are using pyads for this, it needs to be updated to use plc.read_by_name
    # and also needs to be called within the plc_access_lock.
    # Assuming this function is not actively used with the pyads 'plc' object for now.
    non_zero_values = []
    # ... (your existing code for this function) ...
    return non_zero_values

def connect_to_plc():
    try:
        # Pass PLC_IP to the connection if that's what works in your minimal script
        plc = pyads.Connection(AMS_NET_ID, ADS_PORT, PLC_IP)
        plc.open()
        print(f"Connected to PLC: {AMS_NET_ID} at {PLC_IP}")
        return plc
    except Exception as e:
        print(f"Error connecting to PLC: {e}")
        traceback.print_exc() # Add traceback for connection errors
        return None

def read_plc_nodes(plc, plc_name):
    """
    Reads various configuration and status data from the PLC.
    This function is called from send_data_continuously, which will hold the lock.
    """
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M:%S")

    data = {}

    type_mapping = {
        "PLCTYPE_BOOL": pyads.PLCTYPE_BOOL,
        "PLCTYPE_INT": pyads.PLCTYPE_INT,
        "PLCTYPE_BYTE": pyads.PLCTYPE_BYTE,
        "PLCTYPE_UINT": pyads.PLCTYPE_UINT,
        "PLCTYPE_WORD": pyads.PLCTYPE_WORD
    }

    # Read all values from PLC and store in `data`
    for var in PYADS_VARIABLES:
        var_name = var['name']
        var_type = type_mapping.get(var['type'])
        try:
            # >>> This read is within the lock held by send_data_continuously <<<
            value = plc.read_by_name(var_name, var_type) if var_type else None
            clean_name = var_name.replace(".PLC_To_Server.", "")
            clean_name = re.sub(r"\[(\d+)\]", r"_\1", clean_name)
            clean_name = clean_name.replace(".", "_")
            data[clean_name] = value
        except Exception as e:
            print(f"Error reading {var_name}: {e}")
            traceback.print_exc()

    # ... (rest of your read_plc_nodes function, which formats data1, data2) ...
    # === PARKING_SITE_CONFIG ===
    formatted_dict1 = {
        "Message_Id": "PARKING_SITE_CONFIG",
        "System_Date": current_date,
        "System_Time": current_time,
        "System_Code_No": plc_name,
        "System_Type": data.get("System_Type"),
        "System_No": data.get("System_No"),
        "Max_Lift_No": data.get("Max_Lift_No"),
        "Max_Floor_No": data.get("Max_Floor_No"),
        "Max_Shuttle_No": data.get("Max_Shuttle_No"),
        "Total_Parking_Slots": data.get("Total_Parking_Slots"),
        "Slots_By_Type": [data.get(f"Type{i}_Slots") for i in range(1, 8)],
        "Total_Parked_Slots": data.get("Total_Parked_Slots"),
        "Parked_Slots_By_Type": [data.get(f"Type{i}_Parked_Slots") for i in range(1, 8)],
        "Total_Empty_Slots": data.get("Total_Empty_Slots"),
        "Empty_Slots_By_Type": [data.get(f"Type{i}_Empty_Slots") for i in range(1, 8)],
        "Total_Dead_Slots": data.get("Total_Dead_Slots"),
        "Dead_Slots_By_Type": [data.get(f"Type{i}_Dead_Slots") for i in range(1, 8)],
        "Total_Booked_Slots": data.get("Total_Booked_Slots"),
        "Booked_Slots_By_Type": [data.get(f"Type{i}_Booked_Slots") for i in range(1, 8)],
    }

    # === QUEUE_STATUS_UPDATES ===
    queue_data_list = []
    for i in range(1, 110):
        token_no = data.get(f"Request_Queue_Status_{i}_TokenNo")
        if token_no in (None, 0, 9999):
            continue
        estimated_time = data.get(f"Request_Queue_Status_{i}_Estimated_Time")
        request_type = data.get(f"Request_Queue_Status_{i}_Request_Type")
        in_progress = data.get(f"Request_Queue_Status_{i}_Request_In_Progress")
        lift_no = data.get(f"Request_Queue_Status_{i}_Lift_No")
        queue_data_list.append({
            "Token_No": token_no,
            "ETA": estimated_time,
            "Request_Type": request_type,
            "Request_In_Progress": in_progress,
            "Lift_No": lift_no if lift_no not in (None, 0) else "NULL"
        })
    formatted_dict2 = {
        "Message_Id": "QUEUE_STATUS_UPDATES",
        "System_Date": current_date,
        "System_Time": current_time,
        "System_Code_No": plc_name,
        "System_Type": data.get("System_Type", "0"),
        "System_No": data.get("System_No", "0"),
        "Queue_Data": queue_data_list,
    }
   
    parking_map = create_parking_map_from_file(plc, plc_name, current_date, current_time, "parking_maps.txt", queue_data_list)
    return formatted_dict1, formatted_dict2, parking_map
   
def create_parking_map_from_file(plc, plc_name, current_date, current_time, parking_map_file, queue_data_list):
    """
    Creates the parking map data by reading from PLC.
    This function is called from read_plc_nodes, which will be within the lock.
    """
    try:
        with open(parking_map_file, 'r') as f:
            parking_map_nodes = json.load(f)

        non_zero_token_values = []
        for node_info in parking_map_nodes:
            var_name = node_info['name']
            data_type_str = node_info['type']
            data_type = getattr(pyads, data_type_str, None)
            if data_type:
                try:
                    # >>> This read is within the lock held by send_data_continuously <<<
                    value = plc.read_by_name(var_name, data_type)
                    if value is not None and value != 0:
                        non_zero_token_values.append(value)
                except Exception as read_err:
                    print(f"Error reading {var_name}: {read_err}")
                    traceback.print_exc()
            else:
                print(f"Warning: Unknown data type '{data_type_str}' for {var_name}, skipping.")

        perform_parking_map_resync = 0
        try:
            # >>> This read is within the lock held by send_data_continuously <<<
            read_parking_map_value = plc.read_by_name(".PLC_To_Server.Read_Parking_Map", pyads.PLCTYPE_BOOL)
            if read_parking_map_value:
                perform_parking_map_resync = 1
                try:
                    # >>> These writes are within the lock held by send_data_continuously <<<
                    plc.write_by_name(".Server_To_PLC.Read_Parking_Map_Ack", True, pyads.PLCTYPE_BOOL)
                except Exception as ack_err:
                    print(f"Error writing Read_Parking_Map_Ack: {ack_err}")
                    traceback.print_exc()
                try:
                    # >>> These writes are within the lock held by send_data_continuously <<<
                    plc.write_by_name(".Server_To_PLC.Read_Parking_Map_Ack", False, pyads.PLCTYPE_BOOL)
                except Exception as reset_ack_err:
                    print(f"Error resetting Read_Parking_Map_Ack: {reset_ack_err}")
                    traceback.print_exc()
        except Exception as resync_err:
            print(f"Error handling resync logic: {resync_err}")
            traceback.print_exc()

        parking_map = {
            "Message_Id": "PARKING_MAP",
            "System_Date": current_date,
            "System_Time": current_time,
            "System_Code_No": plc_name,
            "System_Type": "0",
            "System_No": "0",
            "Is_PLC_Connected": "1",
            "Perform_Parking_Map_Resync": perform_parking_map_resync,
            "Token_No": non_zero_token_values,
            "Queue_Data": queue_data_list
        }
        return parking_map

    except FileNotFoundError:
        print(f"Error: {parking_map_file} not found.")
        return {}
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {parking_map_file}.")
        return {}
    except Exception as e:
        print(f"Unexpected error creating parking map: {e}")
        traceback.print_exc()
        return {}
   
def read_request_type(plc):
    """
    Reads the Request_Type from PLC and maps it to a different value.
    This function assumes it's called within a PLC lock.
    """
    try:
        # >>> This read is within the lock held by process_queue <<<
        request_type_value = plc.read_by_name(".Server_To_PLC.Request_Data.Request_Type", pyads.PLCTYPE_BYTE)
        
        # Map the request type values
        if request_type_value == 1:
            return 3
        elif request_type_value == 4:
            return 6
        elif request_type_value == 2:
            return 2
        elif request_type_value == 3:
            return 5
        
        # If no mapping was applied, return the original value
        return request_type_value

    except Exception as e:
        print(f"❌ Error reading Request_type value from PLC: {e}")
        traceback.print_exc()
        return None

def write_to_plc(plc, data, type_mapping):
    """
    Writes IoT message values to Beckhoff PLC nodes and handles acknowledgment logic.
    This function is designed to be called within a thread-safe lock (e.g., plc_access_lock).
    
    Args:
        plc (pyads.Connection): The active pyads PLC connection object.
        data (dict): The dictionary containing data received from IoT Hub.
                     Expected keys: "Token_No", "Car_Type_Value", "Request_Type_Value".
        type_mapping (dict): A dictionary mapping string type names (e.g., "PLCTYPE_INT")
                             to pyads PLC type constants.
    """
    # Hardcoded nodes to write to the PLC
    WRITE_NODES = [
        {"name": ".Server_To_PLC.Request_Data.Token_No", "type": "PLCTYPE_INT"},
        {"name": ".Server_To_PLC.Request_Data.Car_Type", "type": "PLCTYPE_BYTE"},
        {"name": ".Server_To_PLC.Request_Data.Request_Type", "type": "PLCTYPE_BYTE"},
        # .Server_To_PLC.Add_Request is handled separately below as a boolean toggle
    ]

    # Data mapping for clean key matching from incoming 'data' dict to PLC variable names' last part
    data_key_mapping = {
        "Token_No": "Token_No",
        "Car_Type": "Car_Type_Value",
        "Request_Type": "Request_Type_Value"
    }

    try:
        print("🚀 Starting Beckhoff write operation...")

        # Apply the request type mapping before writing
        request_type_plc_map = {3: 1, 2: 2, 6: 4, 5: 3}
        if "Request_Type_Value" in data:
            original_request_type = data["Request_Type_Value"]
            data["Request_Type_Value"] = request_type_plc_map.get(original_request_type, original_request_type)
            print(f"DEBUG: Mapped Request_Type_Value from {original_request_type} to {data['Request_Type_Value']}")

        # 1. Write Request_Data nodes (Token_No, Car_Type, Request_Type)
        for node in WRITE_NODES:
            var_name = node['name']
            var_type = type_mapping.get(node['type'], None)
            key_name_for_mapping = var_name.split('.')[-1]
            mapped_key_from_data = data_key_mapping.get(key_name_for_mapping)

            if mapped_key_from_data and mapped_key_from_data in data:
                try:
                    value_to_write = data[mapped_key_from_data]
                    print(f"DEBUG: Attempting to write '{value_to_write}' (type {var_type}) to '{var_name}'")
                    # >>> This write is within the lock held by process_queue <<<
                    plc.write_by_name(var_name, value_to_write, var_type)
                    print(f"✅ Successfully written '{value_to_write}' to '{var_name}'")
                except pyads.pyads_ex.ADSError as ads_e:
                    print(f"❌ ADSError writing {var_name}: {ads_e} (ADS Error Code: {ads_e.error_code})")
                    traceback.print_exc()
                    raise # Re-raise to be caught by the outer try-except for general failure
                except Exception as e:
                    print(f"❌ General Error writing {var_name}: {e}")
                    traceback.print_exc()
                    raise
            else:
                print(f"⚠️ Skipped writing '{var_name}' - corresponding data key '{mapped_key_from_data}' not found in received data: {data}")

        # 2. Toggle .Server_To_PLC.Add_Request to TRUE
        try:
            print("DEBUG: Attempting to set .Server_To_PLC.Add_Request to TRUE")
            # >>> This write is within the lock held by process_queue <<<
            plc.write_by_name(".Server_To_PLC.Add_Request", True, pyads.PLCTYPE_BOOL)
            print("✅ Successfully set .Server_To_PLC.Add_Request to TRUE")
            time.sleep(0.2)  # Allow PLC to process the request
        except pyads.pyads_ex.ADSError as ads_e:
            print(f"❌ ADSError writing .Server_To_PLC.Add_Request (TRUE): {ads_e} (ADS Error Code: {ads_e.error_code})")
            traceback.print_exc()
            raise
        except Exception as e:
            print(f"❌ General Error writing .Server_To_PLC.Add_Request (TRUE): {e}")
            traceback.print_exc()
            raise

        # 3. Read Acknowledgment and other relevant data from PLC
        request_ack = None
        token_no_from_plc = None
        system_code_no = None
        request_type_from_plc = None

        try:
            # >>> These reads are within the lock held by process_queue <<<
            request_ack = plc.read_by_name(".PLC_To_Server.Request_Ack", pyads.PLCTYPE_BYTE)
            print(f"📥 Request_Ack read from PLC: {request_ack}")

            token_no_from_plc = plc.read_by_name(".Server_To_PLC.Request_Data.Token_No", pyads.PLCTYPE_INT)
            print(f"📥 Token_No read from PLC: {token_no_from_plc}")

            system_code_no = plc.read_by_name(".PLC_To_Server.System_Code_No", pyads.PLCTYPE_WORD)
            print(f"📥 System_Code_No read from PLC: {system_code_no}")
            
            # read_request_type also contains plc.read_by_name, so it's protected by this outer lock
            request_type_from_plc = read_request_type(plc)
            print(f"📥 Mapped Request_Type read from PLC: {request_type_from_plc}")

        except pyads.pyads_ex.ADSError as ads_e:
            print(f"❌ ADSError reading acknowledgment data: {ads_e} (ADS Error Code: {ads_e.error_code})")
            traceback.print_exc()
            # Don't re-raise here, as we still want to try resetting Add_Request
        except Exception as e:
            print(f"❌ General Error reading acknowledgment data: {e}")
            traceback.print_exc()

        # 4. Reset .Server_To_PLC.Add_Request to FALSE and send acknowledgment
        if request_ack is not None and request_ack > 0:
            try:
                print("DEBUG: Attempting to reset .Server_To_PLC.Add_Request to FALSE")
                # >>> This write is within the lock held by process_queue <<<
                plc.write_by_name(".Server_To_PLC.Add_Request", False, pyads.PLCTYPE_BOOL)
                print("✅ Successfully reset .Server_To_PLC.Add_Request to FALSE")
                time.sleep(0.05) # Small delay after reset

                # Prepare and send acknowledgment message
                current_date, current_time = get_current_date_time()
                ack_message = {
                    "Message_Id": "REQUEST_ACKNOWLEDGEMENT",
                    "System_Date": current_date,
                    "System_Time": current_time,
                    "System_Code_No": system_code_no,
                    "System_Type": "0", # Hardcoded as per your original
                    "System_No": "0",   # Hardcoded as per your original
                    "Token_No": token_no_from_plc,
                    "Request_Type_Value": request_type_from_plc,
                    "Ack_Status": request_ack
                }
                send_to_azure_iot_hub(ack_message, custom_c) # Use the global custom_c
                print("📤 Sent acknowledgment to Azure IoT Hub")

            except pyads.pyads_ex.ADSError as ads_e:
                print(f"❌ ADSError during Add_Request reset or ACK send: {ads_e} (ADS Error Code: {ads_e.error_code})")
                traceback.print_exc()
            except Exception as e:
                print(f"❌ General Error during Add_Request reset or ACK send: {e}")
                traceback.print_exc()
        else:
            print("⚠️ Request_Ack not received or not positive, skipping acknowledgment send.")

        print("👍 Beckhoff write operation cycle completed.")

    except pyads.pyads_ex.ADSError as ads_e:
        print(f"❌ General write ADSError in write_to_plc function: {ads_e} (ADS Error Code: {ads_e.error_code})")
        traceback.print_exc()
    except Exception as e:
        print(f"❌ General write error in write_to_plc function: {e}")
        traceback.print_exc()

# Send data to Azure IoT Hub
def send_to_azure_iot_hub(json_output, client):
    try:
        if client is None:
            print("⚠️ Azure IoT Hub client is not initialized. Skipping message send.")
            return

        json_str = json.dumps(json_output)
        message = Message(json_str)
        client.send_message(message)
        print(f"Message sent to Azure IoT Hub: {json_output}")

    except Exception as e:
        print(f"Error sending message to Azure IoT Hub: {e}")
        traceback.print_exc()

# Process request queue for writing to PLC
def process_queue(plc):
    # Define type mapping here as well
    type_mapping = {
        "PLCTYPE_INT": pyads.PLCTYPE_INT,
        "PLCTYPE_BYTE": pyads.PLCTYPE_BYTE,
        "PLCTYPE_BOOL": pyads.PLCTYPE_BOOL
    }

    while True:
        data = request_queue.get()
        if data is None:
            break  # Exit signal
        
        # Add a small delay BEFORE acquiring the lock and writing
        # This gives the system a moment if the port is in TIME_WAIT
        time.sleep(0.5) # <--- IMPORTANT: Increased delay here

        # >>> Acquire the global lock before any PLC operation <<<
        with plc_access_lock:  # Use lock to prevent concurrent access
            write_to_plc(plc, data, type_mapping)
        request_queue.task_done()

# Continuously read from PLC and send data to Azure
def send_data_continuously(interval, plc):
    while not stop_thread.is_set():
        start = time.time()
        plc_name = "PRT79"

        try:
            # >>> Acquire the global lock for ALL PLC operations in this thread <<<
            with plc_access_lock:  # Use lock for all reading/writing operations
                # --- Heartbeat logic ---
                # All these reads/writes are now protected by plc_access_lock
                maintenance_mode_value = plc.read_by_name(".PLC_To_Server.Maintenance_Mode", pyads.PLCTYPE_BOOL)
                
                hbr_value = plc.read_by_name(".PLC_To_Server.Heartbeat", pyads.PLCTYPE_BYTE)
                plc.write_by_name(".Server_To_PLC.Heartbeat", hbr_value, pyads.PLCTYPE_BYTE)
                time.sleep(0.01) # Small delay after heartbeat write
                hbr_new_value = plc.read_by_name(".PLC_To_Server.Heartbeat", pyads.PLCTYPE_BYTE)

                # Determine PLC connection status
                is_plc_connected = 1 if hbr_new_value != hbr_value and maintenance_mode_value == 0 else 0

                # Toggle new heartbeat value back
                plc.write_by_name(".Server_To_PLC.Heartbeat", hbr_new_value, pyads.PLCTYPE_BYTE)
                time.sleep(0.05) # Small delay after heartbeat reset

                if not is_plc_connected:
                    print(f"⚠️ PLC '{plc_name}' not connected. Skipping data read.")
                    # If not connected, release the lock and continue to next cycle
                    continue # This will exit the 'with' block and loop again

                # --- Data sending logic ---
                # read_plc_nodes itself contains plc.read_by_name calls,
                # so it must be called within the plc_access_lock.
                data1, data2, parking_map = read_plc_nodes(plc, plc_name)
                
            # These send operations are NOT PLC operations, so they can be outside the lock
            t2 = time.time()
            for dataset in (data1, data2, parking_map):
                if dataset:
                    send_to_azure_iot_hub(dataset, custom_c)
            print(f"⏱ Azure send took: {time.time() - t2:.2f} seconds")

        except Exception as e:
            print(f"❌ Error in PLC '{plc_name}' loop: {e}")
            traceback.print_exc()

        # --- Cycle timing ---
        elapsed = time.time() - start
        print(f"⏱ Total cycle time: {elapsed:.2f} seconds")

        if elapsed < interval:
            time.sleep(interval - elapsed)
 
def on_message_received(message):
    try:
        raw_data = message.data.decode('utf-8').strip()
        print(f"📩 Received message from Azure IoT Hub: {raw_data}")
 
        data = json.loads(raw_data)  # Convert message to Python dict
        print(f"Actual received data: {data}")
 
        # Add the request to the queue with hardcoded Add_Request set to True
        non_plc_data = {
            "Token_No": data.get("Token_No"),
            "Car_Type_Value": data.get("Car_Type_Value"),
            "Request_Type_Value": data.get("Request_Type_Value"),
            "Add_Request": True # This key is used in write_to_plc for the toggle
        }
 
        # Ensure no None values in the data dictionary
        if all(value is not None for value in non_plc_data.values()):
            print(f"📌 Adding to request queue: {non_plc_data}")
            request_queue.put(non_plc_data)
        else:
            print(f"⚠️ Skipped adding to queue due to missing data: {non_plc_data}")
 
    except Exception as e:
        print(f"❌ Error processing Azure message: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    c = IoTHubDeviceClient.create_from_connection_string(CONNECTION_STRING)
    custom_c = c # Assign the client globally

    signal.signal(signal.SIGINT, lambda sig, frame: stop_thread.set())
    signal.signal(signal.SIGTERM, lambda sig, frame: stop_thread.set())

    # >>> Set the local AMS Net ID for your Raspberry Pi <<<
    # This must match the AMS Net ID configured in the TwinCAT static route for your Pi.
    pyads.set_local_address('192.168.1.55.1.1') # <--- CONFIRM THIS IS YOUR PI'S ACTUAL AMS NET ID

    plc = connect_to_plc() # This calls pyads.Connection and plc.open()
    if not plc:
        print("Failed to connect to PLC. Exiting.")
        exit()

    # Start threads
    worker_thread = threading.Thread(target=process_queue, args=(plc,))
    worker_thread.start()

    send_data_thread = threading.Thread(target=send_data_continuously, args=(5, plc,))
    send_data_thread.start()

    c.on_message_received = on_message_received
    c.connect() # Connect Azure IoT Hub client

    try:
        send_data_thread.join() # Wait for the send_data_thread to finish
    except KeyboardInterrupt:
        print("🔴 Interrupted. Cleaning up...")
    finally:
        stop_thread.set() # Signal threads to stop
        request_queue.put(None) # Put a sentinel value to unblock worker_thread
        worker_thread.join() # Wait for worker_thread to finish

        try:
            if plc and plc.is_open: # Ensure plc object exists and is open before closing
                plc.close()
                print("🔒 PLC connection closed.")
        except Exception as e:
            print(f"⚠️ Error closing PLC: {e}")
            traceback.print_exc()

        print("✅ Program exited cleanly.")