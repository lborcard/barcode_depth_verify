"""
Script to display and notify when nanopore run reaches a certain number of bases for each barcode.
Uses StatisticsService to monitor yield per barcode.
"""

import argparse
import logging
import sys
import time
from minknow_api.manager import Manager
import minknow_api.statistics_pb2
import minknow_api.protocol_service


import requests

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)



def notify(msg, title="Script"):
    requests.post(f"https://ntfy.sh/{title}",
                  data=msg.encode(),
                  headers={"Title": title})




def monitor_barcodes(connection, acquisition_run_id, target_bases, watch_barcodes=None, allow_run_stop=False):
    """
    Monitors the acquisition run and notifies when barcodes reach the target base count.
    """
    logger.info(f"Monitoring acquisition run: {acquisition_run_id}")
    logger.info(f"Target bases: {target_bases}")
    if watch_barcodes:
        logger.info(f"Watching barcodes: {', '.join(watch_barcodes)}")
    else:
        logger.info("Watching all encountered barcodes.")

    # Track notified barcodes to avoid multiple notifications
    notified = set()

    # We use stream_acquisition_output to get yield summaries split by barcode.
    # We use a small step (e.g., 30s) to get regular updates.
    stream = connection.statistics.stream_acquisition_output(
        acquisition_run_id=acquisition_run_id,
        data_selection=minknow_api.statistics_pb2.DataSelection(step=30),
        split=minknow_api.statistics_pb2.AcquisitionOutputSplit(
            barcode_name=True
        ),
    )

    try:
        stop_run = True
        for response in stream:
            # response is a StreamAcquisitionOutputResponse
            # It contains a list of snapshots (one per split group)
            for snapshot_group in response.snapshots:
                # snapshot_group.filtering contains the split criteria (e.g., barcode name)
                barcode = "unknown"
                for filter_item in snapshot_group.filtering:
                    if filter_item.barcode_name:
                        barcode = filter_item.barcode_name
                        break

                if watch_barcodes and barcode not in watch_barcodes:
                    logger.info(f"Ignoring barcode {barcode} not in watch list.")
                    continue

                if barcode in notified:
                    continue

                # The latest snapshot in this group
                if not snapshot_group.snapshots:
                    continue

                latest_snapshot = snapshot_group.snapshots[-1]
                # basecalled_pass_bases is the usual metric for "reached X bases"
                current_bases = latest_snapshot.yield_summary.basecalled_pass_bases
                if current_bases < target_bases:
                    stop_run = False
                    print(f"Barcode {barcode} has {current_bases} bases (Target: {target_bases})")
                elif current_bases >= target_bases:

                    print(
                        f"\n*** NOTIFICATION: Barcode {barcode} has reached {current_bases} bases (Target: {target_bases}) ***\n")
                    notified.add(barcode)


                # get user input to stop the program

            # Check if we've notified all watched barcodes
            prot = connection.__getattribute__("protocol")
            if watch_barcodes and all(b in notified for b in watch_barcodes):

                notify(f"All watched barcodes have reached the target. Finishing.",title="test1")
                if allow_run_stop:
                    notify(f"Run was stopped", title="test1")
                    prot.stop_protocol()
                    break

    except Exception as e:
        logger.error(f"Error during streaming: {e}")
    finally:
        logger.info("Monitoring stopped.")


def main():
    parser = argparse.ArgumentParser(description="Notify when barcodes reach a target base count.")
    parser.add_argument("--host", default="localhost", help="MinKNOW host (default: localhost)")
    parser.add_argument("--port", type=int, help="MinKNOW port (default: auto-detect)")
    parser.add_argument("--api-token", help="API token for secure connection")
    parser.add_argument("--position", help="Flow cell position (e.g. MN12345 or 'Position 1')")
    parser.add_argument("--run-id", help="Acquisition run ID to monitor (if omitted, monitors the current run)")
    parser.add_argument("--target-bases", type=int, required=True, help="Target number of basecalled pass bases")
    parser.add_argument("--barcodes", nargs='+', help="Specific barcodes to watch (if omitted, watches all)")
    parser.add_argument("--use-insecure", action="store_true", help="Use insecure connection")
    parser.add_argument("--allow-run-stop", action="store_true", help="Allow run stop")

    args = parser.parse_args()

    try:
        credentials = None
        if args.use_insecure:
            import grpc
            credentials = grpc.local_channel_credentials(grpc.LocalConnectionType.LOCAL_TCP)

        manager = Manager(host=args.host, port=args.port, developer_api_token=args.api_token)

        list_positions = manager.flow_cell_positions()
        print(f"Available positions: {[p.description.name for p in list_positions]}")
        if args.position and args.position in [p.description.name for p in list_positions]:
            connection = manager.connect_to(args.position)

        else:
            # Try to find the first active position if none specified
            positions = manager.flow_cell_positions()
            # Print out available positions.
            active_positions = []
            print("Available sequencing positions on %s:%s:" % (args.host, args.port))
            for pos in positions:
                print("%s: %s" % (pos.name, pos.state))

                if pos.running:
                    print("  secure: %s" % pos.description.rpc_ports.secure)
                    active_positions.append(pos)
                    # User could call {pos.connect()} here to connect to the running MinKNOW instance.
            active_positions = [p for p in active_positions if p.description.name]
            print(f'Active positions: {[p.description.name for p in active_positions]}')
            if not active_positions:
                logger.error("No active sequencing runs found. Please specify a position or start a run.")
                return
            connection = active_positions[0].connect()
            logger.info(f"Connected to first active position: {connection}")

        run_id = args.run_id
        if not run_id:
            try:
                run_info = connection.acquisition.get_current_acquisition_run()
                run_id = run_info.run_id
            except Exception:
                logger.error("No acquisition run is currently active on this position.")
                return

        monitor_barcodes(connection, run_id, args.target_bases, args.barcodes, args.allow_run_stop)

    except Exception as e:
        logger.error(f"Failed to connect or monitor: {e}")


if __name__ == "__main__":
    main()