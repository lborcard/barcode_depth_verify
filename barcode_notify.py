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





def notify_via_ntfy(msg, topic, title="MinKNOW Notification"):
    import requests
    url = f"https://ntfy.sh/{topic}"
    try:
        requests.post(url,
                      data=msg.encode(encoding='utf-8'),
                      headers={"Title": title})
    except Exception as e:
        logger.error(f"Error sending ntfy notification: {e}")


def notify_via_msmtp(msg, recipient, title="MinKNOW Notification",domain='smtp.unibe.ch'):
    import subprocess
    sender = "barcode-notify@unibe.ch"
    email_content = f"From: {sender}\nSubject: {title}\nTo: {recipient}\n\n{msg}"
    try:
        subprocess.run(
            ["msmtp", f"{sender}","--read-envelope-from", "--domain=smtp.unibe.ch", "-t"],
            input=email_content.encode(),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"msmtp failed (exit code {e.returncode}): {e.stderr.decode()}")
    except Exception as e:
        logger.error(f"Error sending email via msmtp: {e}")


def monitor_barcodes(connection, acquisition_run_id, target_bases, watch_barcodes=None, allow_run_stop=False, notify_channel="test1", email_recipient=None, domain=None):
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
                    barcode_display = f"{domain}/{barcode}" if domain else barcode
                    print(f"Barcode {barcode_display} has {current_bases} bases (Target: {target_bases})")
                    msg = f"Barcode {barcode_display} has {current_bases} bases (Target: {target_bases})"
                    if email_recipient:
                        notify_via_msmtp(msg, recipient=email_recipient, title=f"Progress: {barcode_display}")
                elif current_bases >= target_bases:

                    barcode_display = f"{domain}/{barcode}" if domain else barcode
                    msg = f"Barcode {barcode_display} has reached {current_bases} bases (Target: {target_bases})"
                    print(f"\n*** NOTIFICATION: {msg} ***\n")
                    if email_recipient:
                        notify_via_msmtp(msg, recipient=email_recipient, title=f"Target Reached: {barcode_display}")
                    notified.add(barcode)


                # get user input to stop the program

            # Check if we've notified all watched barcodes
            prot = connection.__getattribute__("protocol")
            if watch_barcodes and all(b in notified for b in watch_barcodes):

                msg_finishing = "All watched barcodes have reached the target. Finishing."
                if email_recipient:
                    notify_via_msmtp(msg_finishing, recipient=email_recipient)
                if allow_run_stop:
                    msg_stopped = "Run was stopped"
                    if email_recipient:
                        notify_via_msmtp(msg_stopped, recipient=email_recipient)
                    prot.stop_protocol()
                    break

    except Exception as e:
        logger.error(f"Error during streaming: {e}")
        notify_via_msmtp(f"Error during streaming: {e}", recipient=email_recipient)
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
    parser.add_argument("--notify-channel", default="test1", help="ntfy.sh topic for notifications (default: test1)")
    parser.add_argument("--email", help="Email address for notifications via msmtp")
    parser.add_argument("--domain",default='smtp.unibe.ch', help="Domain to prepend to barcode names in notifications")

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

        monitor_barcodes(connection, run_id, args.target_bases, args.barcodes, args.allow_run_stop, args.notify_channel, args.email, args.domain)

    except Exception as e:
        logger.error(f"Failed to connect or monitor: {e}")


if __name__ == "__main__":
    main()