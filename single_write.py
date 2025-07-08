# Minimal Test Script (for Raspberry Pi debugging only)
import pyads
import time

AMS_NET_ID = '5.51.197.248.1.1' # Your PLC's AMS Net ID
ADS_PORT = 801
PYADS_LOCAL_AMS_NET_ID = '192.168.1.55.1.1' # Your RPi's AMS Net ID
PLC_IP = '192.168.1.1'

pyads.set_local_address(PYADS_LOCAL_AMS_NET_ID)

def test_single_write_cycle():
    plc = None
    try:
        plc = pyads.Connection(AMS_NET_ID, ADS_PORT, PLC_IP)
        plc.open()
        print(f"Connected to PLC: {AMS_NET_ID}")

        # Simulate a simple write operation
        print("Attempting to write .Server_To_PLC.Add_Request to TRUE")
        plc.write_by_name(".Server_To_PLC.Add_Request", True, pyads.PLCTYPE_BOOL)
        print("Successfully written TRUE.")
        time.sleep(0.5) # Give PLC time to process

        print("Attempting to write .Server_To_PLC.Add_Request to FALSE")
        plc.write_by_name(".Server_To_PLC.Add_Request", False, pyads.PLCTYPE_BOOL)
        print("Successfully written FALSE.")

    except pyads.pyads_ex.ADSError as ads_e:
        print(f"❌ ADSError during test_single_write_cycle: {ads_e} (ADS Error Code: {ads_e.error_code})")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"❌ General Error during test_single_write_cycle: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if plc and plc.is_open:
            plc.close()
            print("🔒 PLC connection closed.")

if __name__ == "__main__":
    print("Starting isolated write test...")
    for i in range(5): # Try 5 cycles
        print(f"\n--- Test Cycle {i+1} ---")
        test_single_write_cycle()
        time.sleep(2) # Wait before next cycle to ensure port release
    print("\nIsolated write test completed.")