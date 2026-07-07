# MinKNOW Barcode Notifications

A script to monitor Nanopore sequencing runs and notify when specific barcodes reach a target base count. It uses the MinKNOW `StatisticsService` to track yield per barcode and can optionally stop the sequencing protocol once targets are met.

## Features

- Monitor yield (basecalled pass bases) for all or specific barcodes.
- Send notifications via [ntfy.sh](https://ntfy.sh).
- Automatically stop the MinKNOW protocol when target bases are reached for all watched barcodes.

## Installation

This project uses `uv` for dependency management, but can also be used with `pip`.

### Using uv (recommended)

```bash
uv sync
```

### Using pip

```bash
pip install minknow-api==6.10.1 numpy requests
```

## Usage

Run the script by specifying the target number of bases and optional parameters for your MinKNOW setup.

### Basic Command

To monitor all barcodes and notify when they reach 1,000,000 bases:

```bash
python barcode_notify.py --target-bases 1000000
```

### Watching Specific Barcodes

To only monitor specific barcodes (e.g., barcode01 and barcode02):

```bash
python barcode_notify.py --target-bases 500000 --barcodes barcode01 barcode02
```

### Stopping the Run Automatically

To stop the sequencing protocol once all watched barcodes have reached the target:

```bash
python barcode_notify.py --target-bases 1000000 --barcodes barcode03 --allow-run-stop
```

### Connecting to a Specific Position

If you have multiple flow cells, specify the position:

```bash
python barcode_notify.py --target-bases 1000000 --position "MS00000"
```

### Customizing Notifications

By default, the script sends notifications to `https://ntfy.sh/test1`. You can specify a different channel:

```bash
python barcode_notify.py --target-bases 1000000 --notify-channel my-custom-topic
```

## Command Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--target-bases` | **Required**. Target number of basecalled pass bases. | - |
| `--barcodes` | Specific barcodes to watch (space-separated). Watches all if omitted. | All |
| `--allow-run-stop` | If set, stops the protocol when targets are met. | False |
| `--notify-channel` | ntfy.sh topic for notifications. | test1 |
| `--host` | MinKNOW host. | localhost |
| `--port` | MinKNOW port. | Auto-detect |
| `--position` | Flow cell position name (e.g., "MN12345"). | First active |
| `--run-id` | Acquisition run ID to monitor. | Current run |
| `--api-token` | API token for secure connections. | - |
| `--use-insecure` | Use an insecure gRPC connection. | False |

## Notifications

The script sends notifications to `https://ntfy.sh/test1` by default (or the topic specified by `--notify-channel`). You may want to edit the script to change the default title.
