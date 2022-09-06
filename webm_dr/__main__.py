import os
import re
import shutil
import subprocess
import sys
from argparse import ArgumentParser
from os import PathLike
from pathlib import Path
from random import SystemRandom
from time import time_ns

from loguru import logger
from PIL import Image

random = SystemRandom()


@logger.catch()
class WebmDynamicResolution:
    def __init__(self, mode: int, input_path: PathLike, output_path: PathLike):
        random.seed(time_ns())
        self.base = Path(__file__).resolve().parent.parent
        self.mode = mode
        self.input_path = Path(input_path).resolve()
        self.fps_re = re.compile(r"(\d+\.\d+|\d+) fps")

        self.output_path = Path(output_path).resolve()
        if self.output_path.is_dir():
            os.makedirs(self.output_path, exist_ok=True)

        self.temp = self.base / "tmp"
        os.makedirs(self.temp, exist_ok=True)
        self.concat_path = self.temp / "concat.txt"

    def __call__(self):
        logger.info("Extracting frames...")
        self.extract_frames()
        frame_rate = self.extract_frames()
        frame_bases = self.get_frame_bases()
        logger.info("Resizing frames...")
        self.resize_images(frame_bases)
        logger.info("Frames -> WebMs...")
        self.frames_to_webms(frame_bases, frame_rate)
        logger.info("Concatting WebMs...")
        self.concat_webms(frame_bases)

    def extract_frame_rate(self, out: str) -> str:
        lines = out.split("\n")
        for line in lines:
            if (l_ := re.sub(r"^\s+", "", line).lower()).startswith("stream"):
                match = self.fps_re.search(l_)
                if match is not None:
                    return match.groups()[0]
        raise ValueError("No regex match for frame rate.")

    def extract_frames(self) -> str:
        out_path = self.temp / "out%04d.png"
        cmd = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", str(self.input_path), str(out_path)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        return self.extract_frame_rate(cmd.stdout)

    def get_frame_bases(self) -> list[Path]:
        return list(Path(self.temp).glob("*.png"))

    def resize_images(self, frame_bases: list[Path]):
        for i, base in enumerate(frame_bases):
            res_image_path = base.parent / f"{base.stem}_r{base.suffix}"
            with Image.open(base) as f:
                if i == 0:
                    x, y = f.size
                    shutil.copy2(base, res_image_path)
                    continue
                match self.mode:
                    case 1:
                        img = f.resize(
                            (random.randint(50, 1000), random.randint(50, 1000)), resample=Image.Resampling.LANCZOS
                        )
                    case 2:
                        x += 20
                        y += 20
                        img = f.resize((x, y), resample=Image.Resampling.LANCZOS)
                img.save(res_image_path)

    def frames_to_webms(self, frame_bases: list[Path], frame_rate: str):
        for base in frame_bases:
            in_filename = base.parent / f"{base.stem}_r{base.suffix}"
            out_filename = base.parent / f"{base.stem}.webm"
            cmd = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-framerate",
                    frame_rate,
                    "-f",
                    "image2",
                    "-i",
                    str(in_filename),
                    "-c:v",
                    "libvpx-vp9",
                    "-pix_fmt",
                    "yuva420p",
                    str(out_filename),
                ],
                text=True,
                stderr=subprocess.PIPE,
            )
            if cmd.returncode != 0:
                logger.error(cmd.stderr)
                sys.exit(cmd.returncode)

    def concat_webms(self, frame_bases: list[Path]):
        with open(self.concat_path, "w+") as f:
            for base in frame_bases:
                line = f"file {base.stem}.webm\n"
                f.write(line)
        cmd = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(self.concat_path),
                "-c",
                "copy",
                "-y",
                str(self.output_path),
            ],
            text=True,
            stderr=subprocess.PIPE,
        )
        if cmd.returncode != 0:
            logger.error(cmd.stderr)
            sys.exit(cmd.returncode)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("-m", "--mode", type=int, help="1 = random, 2 = growing. default = 1", default=1)
    parser.add_argument("-o", "--output-path", type=str, help="Path to write output file to.")
    parser.add_argument("input_path", metavar="input_path", type=str, nargs="+", help="Path of input file.")
    args = parser.parse_args()
    if args.mode not in [1, 2]:
        raise ValueError("Mode must be 1 or 2.")
    if not args.output_path.lower().endswith(".webm"):
        raise ValueError('Output file extension must be ".webm"')
    webm_dr = WebmDynamicResolution(mode=args.mode, input_path=args.input_path[0], output_path=args.output_path)
    try:
        webm_dr()
    except Exception as e:
        logger.exception(e)
    finally:
        if webm_dr.temp.exists():
            shutil.rmtree(webm_dr.temp)
