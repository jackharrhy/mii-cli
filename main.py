#!/usr/bin/env python3
"""
Mii Extractor CLI - A tool for extracting .mii files from Dolphin dumped data
"""

import os
import struct
import csv
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, TaskID

app = typer.Typer(help="Extract and analyze Mii files from Wii/Dolphin files")
console = Console()


class MiiFileReader:
    """Reader for extracting metadata from .mii files"""

    def __init__(self, file_path: Path):
        with open(file_path, "rb") as f:
            self.data = f.read()

        # Color mapping based on C# array
        self.colors = [
            "Red",
            "Orange",
            "Yellow",
            "Green",
            "DarkGreen",
            "Blue",
            "LightBlue",
            "Pink",
            "Purple",
            "Brown",
            "White",
            "Black",
        ]

    def read_string(self, offset: int, length: int) -> str:
        """Read UTF-16BE string from the file data"""
        string_data = self.data[offset : offset + length]
        # Find the first null terminator (0x0000 in UTF-16BE)
        null_pos = string_data.find(b"\x00\x00")
        if null_pos != -1:
            # Ensure we align to 2-byte boundaries for UTF-16
            if null_pos % 2 != 0:
                null_pos -= 1
            string_data = string_data[: null_pos + 2]

        # Convert from UTF-16BE and remove null terminators
        return string_data.decode("utf-16be").rstrip("\x00")

    def read_mii_name(self) -> str:
        """Read Mii name starting at offset 2"""
        return self.read_string(2, 20)

    def read_creator_name(self) -> str:
        """Read creator name starting at offset 54"""
        return self.read_string(54, 20)

    def read_mii_metadata(self) -> list:
        """Read and parse Mii metadata from first 2 bytes"""
        # Read first 2 bytes and convert to binary string
        metadata_bytes = self.data[0:2]
        binary_str = "".join(format(b, "08b") for b in metadata_bytes)

        # Extract metadata fields
        is_girl = int(binary_str[1], 2)
        birth_month = int(binary_str[2:6], 2)
        birth_day = int(binary_str[6:11], 2)
        favorite_color = int(binary_str[11:15], 2)
        is_favorite = int(binary_str[15], 2)

        return [is_girl, birth_month, birth_day, favorite_color, is_favorite]

    def read_mii_id(self) -> bytes:
        """Read 4-byte Mii ID starting at offset 24"""
        return self.data[24:28]

    def get_color_name(self, color_index: int) -> str:
        """Get color name from color index"""
        if 0 <= color_index < len(self.colors):
            return self.colors[color_index]
        return f"Unknown ({color_index})"


class MiiType(Enum):
    """Enum describing different Mii database types with their configurations"""

    WII_PLAZA = ("RFL_DB.dat", 0x4, 74, 0, 100, "WII_PL")
    WII_PARADE = ("RFL_DB.dat", 0x1F1E0, 64, 10, 10_000, "WII_PA")
    WIIU_MAKER = ("FFL_ODB.dat", 0x8, 92, 0, 3_000, "WIIU_MA")
    _3DS_MAKER = ("CFL_DB.dat", 0x8, 92, 0, 100, "3DS_MA")

    def __init__(
        self, source: str, offset: int, size: int, padding: int, limit: int, prefix: str
    ):
        self.SOURCE = source
        self.OFFSET = offset
        self.SIZE = size
        self.PADDING = padding
        self.LIMIT = limit
        self.PREFIX = prefix

    @property
    def display_name(self) -> str:
        """Return a human-readable name for the Mii type"""
        return self.name.lower().replace("_", "-")


def extract_miis_from_type(
    mii_type: MiiType, input_file: Optional[Path] = None, output_dir: Path = Path(".")
) -> int:
    """Extract Miis from a specific database type"""
    source_file = input_file or Path(mii_type.SOURCE)

    if not source_file.exists():
        console.print(f"[red]Error: {source_file} not found[/red]")
        return 0

    mii_padding = bytearray(mii_type.PADDING)
    empty_mii = bytearray(mii_type.SIZE)
    mii_count = 0
    is_active = True

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        with open(source_file, "rb") as infile:
            infile.seek(mii_type.OFFSET)

            with Progress() as progress:
                task = progress.add_task(
                    f"[cyan]Extracting {mii_type.PREFIX} Miis...", total=mii_type.LIMIT
                )

                while is_active and mii_count < mii_type.LIMIT:
                    mii_data = infile.read(mii_type.SIZE)

                    if len(mii_data) < mii_type.SIZE or mii_data == empty_mii:
                        is_active = False
                    else:
                        mii_name = f"{mii_type.PREFIX}{mii_count:05d}.mii"
                        output_path = output_dir / mii_name

                        with open(output_path, "wb") as outfile:
                            outfile.write(mii_data + mii_padding)

                        mii_count += 1
                        progress.update(task, advance=1)

    except PermissionError:
        console.print(f"[red]Error: Permission denied accessing {source_file}[/red]")
        return 0

    console.print(
        f"[green]Extracted {mii_count} {mii_type.PREFIX} Miis to {output_dir}[/green]"
    )
    return mii_count


@app.command()
def extract(
    mii_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Specific Mii type to extract (wii-plaza, wii-parade, wiiu-maker, 3ds-maker)",
    ),
    input_file: Optional[Path] = typer.Option(
        None, "--input", "-i", help="Custom input database file path"
    ),
    output_dir: Path = typer.Option(
        Path("."), "--output", "-o", help="Output directory for extracted .mii files"
    ),
):
    """Extract Mii files from Nintendo console database dumps"""

    if mii_type:
        # Extract specific type
        try:
            # Handle the special case of 3DS_MAKER
            enum_name = mii_type.upper().replace("-", "_")
            if enum_name == "3DS_MAKER":
                selected_type = MiiType._3DS_MAKER
            else:
                selected_type = MiiType[enum_name]

            total_extracted = extract_miis_from_type(
                selected_type, input_file, output_dir
            )

        except KeyError:
            console.print(f"[red]Error: Unknown Mii type '{mii_type}'[/red]")
            console.print("Valid types: wii-plaza, wii-parade, wiiu-maker, 3ds-maker")
            raise typer.Exit(1)
    else:
        # Extract all types
        console.print("[bold]Extracting from all supported database types...[/bold]")
        total_extracted = 0

        for mii_enum in MiiType:
            extracted = extract_miis_from_type(mii_enum, None, output_dir)
            total_extracted += extracted

        console.print(
            f"\n[bold green]Total Miis extracted: {total_extracted}[/bold green]"
        )


def get_mii_mode(filename: str, file_size: int) -> bool:
    """Determine if a Mii file is from Wii (True) or 3DS/WiiU (False)"""
    if file_size == 74:
        return True  # Wii Mii
    elif file_size == 92:
        return False  # 3DS/WiiU Mii
    else:
        raise ValueError(f"{filename}'s format is unknown (size: {file_size})")


def get_mii_seconds(file_handle, is_wii_mii: bool) -> int:
    """Extract timestamp seconds from Mii file"""
    multiplier = 4 if is_wii_mii else 2
    seek_pos = 0x18 if is_wii_mii else 0xC

    file_handle.seek(seek_pos)
    str_id = file_handle.read(4).hex()
    int_id = int(str_id[1:], 16)
    return int_id * multiplier


def get_mii_datetime(seconds: int, is_wii_mii: bool) -> datetime:
    """Convert Mii timestamp seconds to datetime"""
    base_date = datetime(2006, 1, 1) if is_wii_mii else datetime(2010, 1, 1)
    shift = timedelta(seconds=seconds)
    return base_date + shift


@app.command()
def times(
    directory: Path = typer.Option(
        Path("."), "--directory", "-d", help="Directory containing .mii files"
    ),
):
    """Calculate and display creation times for Mii files"""

    if not directory.exists():
        console.print(f"[red]Error: Directory {directory} does not exist[/red]")
        raise typer.Exit(1)

    mii_files = list(directory.glob("*.mii"))
    if not mii_files:
        console.print(f"[yellow]No .mii files found in {directory}[/yellow]")
        return

    console.print(f"[bold]Analyzing {len(mii_files)} .mii files...[/bold]\n")

    table = Table(title="Mii Creation Times")
    table.add_column("Filename", style="cyan")
    table.add_column("Creation Time", style="green")
    table.add_column("Type", style="blue")

    successful_analyses = 0

    for mii_file in sorted(mii_files):
        try:
            file_size = mii_file.stat().st_size
            is_wii_mii = get_mii_mode(mii_file.name, file_size)

            with open(mii_file, "rb") as infile:
                seconds = get_mii_seconds(infile, is_wii_mii)
                creation_time = get_mii_datetime(seconds, is_wii_mii)

                mii_type = "Wii" if is_wii_mii else "3DS/WiiU"
                table.add_row(
                    mii_file.name, creation_time.strftime("%Y-%m-%d %H:%M:%S"), mii_type
                )
                successful_analyses += 1

        except Exception as err:
            console.print(f"[red]Error analyzing {mii_file.name}: {err}[/red]")

    console.print(table)
    console.print(
        f"\n[green]Successfully analyzed {successful_analyses}/{len(mii_files)} files[/green]"
    )


@app.command()
def metadata(
    directory: Path = typer.Option(
        Path("."), "--directory", "-d", help="Directory containing .mii files"
    ),
    single_file: Optional[Path] = typer.Option(
        None, "--file", "-f", help="Analyze a single .mii file"
    ),
    csv_output: Optional[Path] = typer.Option(
        None, "--csv", "-c", help="Save results to CSV file"
    ),
):
    """Display metadata for Mii files (names, colors, birthdays, etc.)"""

    if single_file:
        # Analyze single file
        if not single_file.exists():
            console.print(f"[red]Error: File {single_file} does not exist[/red]")
            raise typer.Exit(1)

        try:
            reader = MiiFileReader(single_file)

            mii_name = reader.read_mii_name()
            creator_name = reader.read_creator_name()
            metadata = reader.read_mii_metadata()
            mii_id = reader.read_mii_id()
            color_name = reader.get_color_name(metadata[3])

            table = Table(title=f"Metadata for {single_file.name}")
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="green")

            table.add_row("Mii Name", mii_name)
            table.add_row("Creator Name", creator_name)
            table.add_row("Gender", "Female" if metadata[0] else "Male")
            table.add_row("Birth Month", str(metadata[1]) if metadata[1] else "Not set")
            table.add_row("Birth Day", str(metadata[2]) if metadata[2] else "Not set")
            table.add_row("Favorite Color", color_name)
            table.add_row("Is Favorite", "Yes" if metadata[4] else "No")
            table.add_row("Mii ID", mii_id.hex().upper())

            console.print(table)

        except Exception as e:
            console.print(f"[red]Error reading {single_file}: {e}[/red]")
            raise typer.Exit(1)

    else:
        # Analyze directory
        if not directory.exists():
            console.print(f"[red]Error: Directory {directory} does not exist[/red]")
            raise typer.Exit(1)

        mii_files = list(directory.glob("*.mii"))
        if not mii_files:
            console.print(f"[yellow]No .mii files found in {directory}[/yellow]")
            return

        console.print(f"[bold]Analyzing {len(mii_files)} .mii files...[/bold]\n")

        results = []
        successful_analyses = 0

        for mii_file in sorted(mii_files):
            try:
                reader = MiiFileReader(mii_file)

                mii_name = reader.read_mii_name()
                creator_name = reader.read_creator_name()
                metadata = reader.read_mii_metadata()
                mii_id = reader.read_mii_id()
                color_name = reader.get_color_name(metadata[3])

                gender = "Female" if metadata[0] else "Male"
                gender_short = "F" if metadata[0] else "M"
                birthday = (
                    f"{metadata[1]}/{metadata[2]}"
                    if metadata[1] and metadata[2]
                    else "Not set"
                )

                result_data = {
                    "filename": mii_file.name,
                    "mii_name": mii_name or "Unnamed",
                    "creator_name": creator_name or "Unknown",
                    "is_girl": metadata[0],
                    "gender": gender,
                    "birth_month": metadata[1],
                    "birth_day": metadata[2],
                    "birthday": birthday,
                    "favorite_color": color_name,
                    "favorite_color_index": metadata[3],
                    "is_favorite": metadata[4],
                    "mii_id": mii_id.hex().upper(),
                }

                results.append(result_data)
                successful_analyses += 1

            except Exception as err:
                console.print(f"[red]Error analyzing {mii_file.name}: {err}[/red]")

        if csv_output:
            # Save to CSV
            if results:
                fieldnames = [
                    "filename",
                    "mii_name",
                    "creator_name",
                    "is_girl",
                    "gender",
                    "birth_month",
                    "birth_day",
                    "birthday",
                    "favorite_color",
                    "favorite_color_index",
                    "is_favorite",
                    "mii_id",
                ]

                with open(csv_output, "w", newline="", encoding="utf-8") as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(results)

                console.print(
                    f"[green]Saved metadata for {len(results)} .mii files to {csv_output}[/green]"
                )
            else:
                console.print("[yellow]No data to save to CSV[/yellow]")
        else:
            # Display table
            table = Table(title="Mii Metadata")
            table.add_column("Filename", style="cyan")
            table.add_column("Mii Name", style="green")
            table.add_column("Creator", style="blue")
            table.add_column("Gender", style="magenta")
            table.add_column("Birthday", style="yellow")
            table.add_column("Favorite Color", style="red")

            for result in results:
                table.add_row(
                    result["filename"],
                    result["mii_name"],
                    result["creator_name"],
                    result["gender"][0],  # Just show M/F for display
                    result["birthday"],
                    result["favorite_color"],
                )

            console.print(table)

        console.print(
            f"\n[green]Successfully analyzed {successful_analyses}/{len(mii_files)} files[/green]"
        )


@app.command()
def info():
    """Display information about supported Mii database types"""

    table = Table(title="Supported Mii Database Types")
    table.add_column("Type", style="cyan")
    table.add_column("Source File", style="green")
    table.add_column("Mii Size", style="blue")
    table.add_column("Max Count", style="yellow")
    table.add_column("Prefix", style="magenta")

    for mii_type in MiiType:
        table.add_row(
            mii_type.display_name,
            mii_type.SOURCE,
            f"{mii_type.SIZE} bytes",
            str(mii_type.LIMIT),
            mii_type.PREFIX,
        )

    console.print(table)
    console.print(
        "\n[dim]Place the appropriate database files in the current directory or specify custom paths with --input[/dim]"
    )


if __name__ == "__main__":
    app()
