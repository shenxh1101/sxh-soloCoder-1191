#!/usr/bin/env python3
import argparse
import os
import sys
import json

from gerber_checker.parser import parse_gerber_file, parse_drill_file, parse_multiple_files
from gerber_checker.renderer import render_layer, render_board
from gerber_checker.drc import DRCEngine
from gerber_checker.config import load_config
from gerber_checker.svg_export import export_layer_svg, export_board_svg
from gerber_checker.metadata import extract_metadata, generate_cam_report
from gerber_checker.diff import diff_gerber_versions


def cmd_ascii(args):
    """Render Gerber layers as ASCII art in terminal."""
    if not args.files:
        print("Error: No input files specified.", file=sys.stderr)
        sys.exit(1)

    board = parse_multiple_files(args.files)

    if args.layer:
        found = None
        for name, layer in board.layers.items():
            if args.layer.lower() in name.lower():
                found = layer
                break
        if found:
            print(render_layer(found))
        else:
            print(f"Layer '{args.layer}' not found. Available: {list(board.layers.keys())}")
    else:
        print(render_board(board))


def cmd_drc(args):
    """Run Design Rule Check on Gerber files."""
    if not args.files:
        print("Error: No input files specified.", file=sys.stderr)
        sys.exit(1)

    rules = load_config(args.config)
    board = parse_multiple_files(args.files)

    engine = DRCEngine(rules)
    report = engine.check_board(board)

    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(report.to_text())

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            if args.format == "json":
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            else:
                f.write(report.to_text())
        print(f"\nReport saved to: {args.output}")


def cmd_svg(args):
    """Export Gerber layers to SVG format."""
    if not args.files:
        print("Error: No input files specified.", file=sys.stderr)
        sys.exit(1)

    board = parse_multiple_files(args.files)

    if args.layer:
        found = None
        for name, layer in board.layers.items():
            if args.layer.lower() in name.lower():
                found = (name, layer)
                break
        if found:
            out_path = args.output or f"{found[0]}.svg"
            export_layer_svg(found[1], out_path)
            print(f"SVG exported to: {out_path}")
        else:
            print(f"Layer '{args.layer}' not found. Available: {list(board.layers.keys())}")
    else:
        out_dir = args.output or "svg_output"
        export_board_svg(board, out_dir)
        print(f"All layers exported to: {out_dir}/")


def cmd_metadata(args):
    """Extract metadata from Gerber files as JSON."""
    if not args.files:
        print("Error: No input files specified.", file=sys.stderr)
        sys.exit(1)

    board = parse_multiple_files(args.files)

    if args.report:
        result = generate_cam_report(board)
    else:
        result = extract_metadata(board)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"Report saved to: {args.output}")
    else:
        print(result)


def cmd_diff(args):
    """Compare two versions of Gerber files."""
    paths_a = args.files_a
    paths_b = args.files_b

    if not paths_a or not paths_b:
        print("Error: Both --files-a and --files-b are required.", file=sys.stderr)
        sys.exit(1)

    report = diff_gerber_versions(paths_a, paths_b,
                                  version_a=args.label_a,
                                  version_b=args.label_b)

    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    elif args.audit:
        print(report.to_audit_text())
    else:
        print(report.to_text())

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            if args.format == "json":
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            elif args.audit:
                f.write(report.to_audit_text())
            else:
                f.write(report.to_text())
        print(f"\nDiff report saved to: {args.output}")


def main():
    parser = argparse.ArgumentParser(
        prog="gerber-check",
        description="PCB Gerber File Viewer & Design Rule Check Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  gerber-check ascii board.gbr                     Render board as ASCII art
  gerber-check ascii board.gbr drill.txt           Render with drill holes
  gerber-check ascii --layer top board.gbr         Render specific layer
  gerber-check drc board.gbr                       Run DRC with default rules
  gerber-check drc -c my_rules.yaml board.gbr      Run DRC with custom rules
  gerber-check svg board.gbr                       Export all layers to SVG
  gerber-check svg --layer top board.gbr -o top.svg Export single layer
  gerber-check meta board.gbr                      Extract metadata as JSON
  gerber-check meta board.gbr -o metadata.json     Save metadata to file
  gerber-check diff --files-a v1/*.gbr --files-b v2/*.gbr  Compare versions
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    p_ascii = subparsers.add_parser("ascii", help="Render Gerber as ASCII art in terminal")
    p_ascii.add_argument("--layer", "-l", help="Render specific layer by name")
    p_ascii.add_argument("files", nargs="*", help="Gerber/drill files to render")

    p_drc = subparsers.add_parser("drc", help="Run Design Rule Check")
    p_drc.add_argument("-c", "--config", help="Path to DRC rules config file (YAML/JSON)")
    p_drc.add_argument("-f", "--format", choices=["text", "json"], default="text", help="Output format")
    p_drc.add_argument("-o", "--output", help="Save report to file")
    p_drc.add_argument("files", nargs="*", help="Gerber/drill files to check")

    p_svg = subparsers.add_parser("svg", help="Export layers to SVG format")
    p_svg.add_argument("--layer", "-l", help="Export specific layer by name")
    p_svg.add_argument("-o", "--output", help="Output file (single layer) or directory (all layers)")
    p_svg.add_argument("files", nargs="*", help="Gerber/drill files to export")

    p_meta = subparsers.add_parser("meta", help="Extract metadata as JSON")
    p_meta.add_argument("-o", "--output", help="Save report to file")
    p_meta.add_argument("--report", action="store_true", help="Generate CAM audit Markdown report")
    p_meta.add_argument("files", nargs="*", help="Gerber/drill files to analyze")

    p_diff = subparsers.add_parser("diff", help="Compare two versions of Gerber files")
    p_diff.add_argument("--files-a", nargs="+", help="Version A: Gerber files")
    p_diff.add_argument("--files-b", nargs="+", help="Version B: Gerber files")
    p_diff.add_argument("--label-a", default="Version A", help="Label for version A")
    p_diff.add_argument("--label-b", default="Version B", help="Label for version B")
    p_diff.add_argument("-f", "--format", choices=["text", "json"], default="text", help="Output format")
    p_diff.add_argument("--audit", action="store_true", help="Output acceptance review format")
    p_diff.add_argument("-o", "--output", help="Save report to file")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    commands = {
        "ascii": cmd_ascii,
        "drc": cmd_drc,
        "svg": cmd_svg,
        "meta": cmd_metadata,
        "diff": cmd_diff,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()