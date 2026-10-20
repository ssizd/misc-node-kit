"""
ComfyUI Custom Node: Wildcard Image Iterator
"""

import os
import re
import json
import random
import importlib.util
from PIL import Image, ImageOps
import numpy as np
import torch



# ============================================================
# 동적 입출력을 위한 헬퍼 클래스들
# ============================================================

class AnyType(str):
    """항상 동등 비교에서 True를 반환하는 특수 타입"""
    def __ne__(self, __value: object) -> bool:
        return False

any_type = AnyType("*")


def _parse_wildcards_config(text):
    text = str(text or "")
    raw_match = re.search(r'"wildcards_dir"\s*:\s*"([^"\r\n]*)"', text)
    raw_value = raw_match.group(1).strip() if raw_match else ""

    # Accept ordinary Windows paths copied with single backslashes even though
    # strict JSON normally requires each backslash to be doubled.
    if raw_value and re.search(r'(?<!\\)\\(?![\\"])', raw_value):
        return raw_value

    try:
        config = json.loads(text)
        if isinstance(config, dict) and str(config.get("wildcards_dir", "")).strip():
            return str(config["wildcards_dir"]).strip()
    except Exception:
        pass
    return raw_value or "wildcards"


def get_wildcards_dir():
    """Load the wildcard directory from wildcard_paths.json."""
    node_dir = os.path.dirname(os.path.abspath(__file__))
    custom_nodes_dir = os.path.dirname(node_dir)
    comfyui_dir = os.path.dirname(custom_nodes_dir)
    config_path = os.path.join(node_dir, "wildcard_paths.json")
    configured_path = "wildcards"

    try:
        if os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8-sig") as f:
                configured_path = _parse_wildcards_config(f.read())
    except Exception as e:
        print(f"[Wildcard Path] 설정 파일을 읽지 못해 기본 경로를 사용합니다: {e}")

    configured_path = os.path.expandvars(os.path.expanduser(configured_path))
    if not os.path.isabs(configured_path):
        configured_path = os.path.join(comfyui_dir, configured_path)
    return os.path.abspath(configured_path)


class FlexibleOptionalInputType(dict):
    """동적 입력 개수를 위한 특수 딕셔너리"""
    def __init__(self, type, data=None):
        self.type = type
        self.data = data or {}
        for k, v in self.data.items():
            self[k] = v

    def __getitem__(self, key):
        if key in self.data:
            return self.data[key]
        return (self.type,)

    def __contains__(self, key):
        return True


class ByPassTypeTuple(tuple):
    """동적 출력을 위한 특수 튜플 - 정의된 개수보다 많이 요청해도 AnyType 반환"""
    def __getitem__(self, index):
        if index > len(self) - 1:
            return AnyType("*")
        return super().__getitem__(index)


class CharNamesTypeTuple(tuple):
    """char_N 이름을 동적으로 생성하는 RETURN_NAMES 튜플"""
    def __getitem__(self, index):
        if index > len(self) - 1:
            return f"char_{index - 1}"
        return super().__getitem__(index)


class FrameSplitNamesTypeTuple(tuple):
    """frames_N / audio_N 이름을 동적으로 생성하는 RETURN_NAMES 튜플 (VideoFromFolderLoader용)"""
    # 인덱스 초과 시 frames_1, frames_2 ... 그 다음 audio_1, audio_2... 순서
    # 하지만 split_count를 모르므로 일단 frames_N으로 반환 (실제 매칭은 JS에서 설정한 슬롯명 기준)
    def __getitem__(self, index):
        if index > len(self) - 1:
            return f"output_{index - 7}"
        return super().__getitem__(index)


class FrameSplitTypesTuple(tuple):
    """동적 출력 타입 튜플 - 인덱스 초과 시 AnyType 반환 (audio/image 모두 허용)"""
    def __getitem__(self, index):
        if index > len(self) - 1:
            return AnyType("*")
        return super().__getitem__(index)


# ============================================================
# 노드 클래스들
# ============================================================


class WildcardImageIterator:
    def __init__(self):
        self.current_image_index = 0
        self.current_wildcard_index = 0
        self.total_iterations = 0
        self.image_files = []
        self.last_image_folder = ""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_folder": ("STRING", {"default": "input_images"}),
                "wildcard_list": ("STRING", {"multiline": True, "default": "prompt 1\nprompt 2\nprompt 3"}),
                "wildcard_count": ("INT", {"default": 1, "min": 1}),
                "image_offset": ("INT", {"default": 0, "min": 0, "max": 999999}),
                "use_subfolders": ("BOOLEAN", {"default": False}),
                "random_flip": ("BOOLEAN", {"default": False}),
                "reset": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING", "STRING", "INT", "INT", "INT", "BOOLEAN")
    RETURN_NAMES = ("current_image", "mask", "current_prompt", "image_filename", "filename_no_ext", "image_index", "wildcard_index", "total_iteration", "is_complete")
    FUNCTION = "iterate"
    CATEGORY = "image/animation"

    def load_image(self, image_path, should_flip=False):
        img = Image.open(image_path)
        if should_flip:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        if img.mode == 'RGBA':
            alpha = np.array(img.getchannel('A')).astype(np.float32) / 255.0
            mask_tensor = torch.from_numpy(alpha)
        else:
            mask_tensor = torch.ones((img.size[1], img.size[0]), dtype=torch.float32)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        img_np = np.array(img).astype(np.float32) / 255.0
        img_tensor = torch.from_numpy(img_np).unsqueeze(0)
        return img_tensor, mask_tensor

    def iterate(self, image_folder, wildcard_list, wildcard_count=1, image_offset=0, use_subfolders=False, random_flip=False, reset=False, seed=0):
        wildcards = [w.strip() for w in wildcard_list.split('\n') if w.strip()] or [""]
        if self.last_image_folder != image_folder or not self.image_files or reset:
            if not os.path.isabs(image_folder):
                import folder_paths
                image_folder = os.path.join(folder_paths.get_input_directory(), image_folder)
            valid_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}
            if os.path.exists(image_folder):
                self.image_files = []
                if use_subfolders:
                    for root, dirs, files in os.walk(image_folder):
                        for f in sorted(files):
                            if os.path.splitext(f.lower())[1] in valid_extensions:
                                self.image_files.append(os.path.join(root, f))
                    self.image_files.sort()
                else:
                    for f in sorted(os.listdir(image_folder)):
                        fp = os.path.join(image_folder, f)
                        if os.path.isfile(fp) and os.path.splitext(f.lower())[1] in valid_extensions:
                            self.image_files.append(fp)
                self.last_image_folder = image_folder
            else:
                raise ValueError(f"이미지 폴더를 찾을 수 없습니다: {image_folder}")
        if reset:
            self.current_image_index = 0
            self.current_wildcard_index = 0
            self.total_iterations = 0
        if not self.image_files:
            raise ValueError("이미지 폴더에 이미지 파일이 없습니다.")
        num_images = len(self.image_files)
        num_wildcards = len(wildcards)
        cycle_offset = image_offset // wildcard_count if wildcard_count > 0 else 0
        actual_image_index = (self.current_image_index + cycle_offset) % num_images
        should_flip = False
        if random_flip:
            random.seed(seed + self.total_iterations)
            should_flip = random.choice([True, False])
        current_image_path = self.image_files[actual_image_index]
        current_image, mask = self.load_image(current_image_path, should_flip)
        current_filename = os.path.basename(current_image_path)
        filename_no_ext = os.path.splitext(current_filename)[0]
        current_prompt = wildcards[self.current_wildcard_index]
        print(f"[Wildcard Iterator] Image {actual_image_index+1}/{num_images} ({current_filename}), Prompt {self.current_wildcard_index+1}/{num_wildcards}")
        self.current_wildcard_index += 1
        if self.current_wildcard_index >= num_wildcards:
            self.current_wildcard_index = 0
            self.current_image_index += 1
        self.total_iterations += 1
        is_complete = self.current_image_index >= num_images
        if is_complete:
            self.current_image_index = 0
            self.current_wildcard_index = 0
        return (current_image, mask, current_prompt, current_filename, filename_no_ext, actual_image_index, self.current_wildcard_index, self.total_iterations, is_complete)


class WildcardFileLoader:
    @classmethod
    def INPUT_TYPES(cls):
        wildcards_dir = get_wildcards_dir()
        wildcard_files = []
        if os.path.exists(wildcards_dir):
            for root, dirs, files in os.walk(wildcards_dir):
                for f in files:
                    if f.endswith('.txt'):
                        wildcard_files.append(os.path.relpath(os.path.join(root, f), wildcards_dir))
            wildcard_files.sort()
        if not wildcard_files:
            wildcard_files = ["prompts.txt"]
        return {
            "required": {
                "wildcard_file": (wildcard_files, {"default": wildcard_files[0]}),
                "mode": (["sequential", "random"], {"default": "sequential"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            }
        }

    RETURN_TYPES = ("STRING", "INT", "INT", "STRING", "STRING")
    RETURN_NAMES = ("wildcard_list", "wildcard_count", "seed", "wildcard_name", "current_line")
    FUNCTION = "load_file"
    CATEGORY = "image/animation"

    @classmethod
    def IS_CHANGED(cls, wildcard_file, mode, seed):
        # 파일 수정 시간을 반환 → 파일이 바뀌면 자동으로 재실행
        try:
            file_path = os.path.join(get_wildcards_dir(), wildcard_file)
            return os.path.getmtime(file_path)
        except Exception:
            return float("nan")  # 파일 없으면 항상 재실행

    def load_file(self, wildcard_file, mode="sequential", seed=0):
        try:
            wildcards_dir = get_wildcards_dir()
            file_path = os.path.join(wildcards_dir, wildcard_file)
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            wildcards = [w.strip() for w in content.split('\n') if w.strip()]
            if not wildcards:
                return ("", 0, seed, "", "")
            if mode == "random":
                random.seed(seed)
                random.shuffle(wildcards)
            elif seed > 0:
                offset = seed % len(wildcards)
                wildcards = wildcards[offset:] + wildcards[:offset]
            # 파일명에서 확장자 제거 (서브폴더 포함 경로에서 파일명만)
            wildcard_name = os.path.splitext(os.path.basename(wildcard_file))[0]
            current_line = wildcards[0]  # seed로 정해진 현재 줄 1개
            print(f"[Wildcard File Loader] '{wildcard_file}'에서 {len(wildcards)}개 로드됨, current_line: '{current_line[:60]}{'...' if len(current_line) > 60 else ''}'")
            return ('\n'.join(wildcards), len(wildcards), seed, wildcard_name, current_line)
        except Exception as e:
            print(f"[Wildcard File Loader] 오류: {str(e)}")
            return ("", 0, seed, "", "")


class WildcardTextProcessor:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": "1girl, __hair__"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "mode": (["seeded", "random"], {"default": "seeded"}),
                "recursive_depth": ("INT", {"default": 5, "min": 0, "max": 20, "step": 1}),
                "missing_behavior": (["keep", "empty"], {"default": "keep"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("STRING",)
    FUNCTION = "process"
    CATEGORY = "text"

    @classmethod
    def IS_CHANGED(cls, text, seed, mode, recursive_depth, missing_behavior):
        wildcards_dir = get_wildcards_dir()
        mtimes = []
        try:
            for root, dirs, files in os.walk(wildcards_dir):
                for f in files:
                    if f.lower().endswith(".txt"):
                        mtimes.append(os.path.getmtime(os.path.join(root, f)))
        except Exception:
            pass
        return (text, seed, mode, recursive_depth, missing_behavior, tuple(sorted(mtimes)))

    def _wildcards_dir(self):
        return get_wildcards_dir()

    def _find_wildcard_file(self, name):
        wildcards_dir = self._wildcards_dir()
        raw = str(name).strip().strip("_").strip().replace("\\", "/")
        if not raw:
            return None

        candidates = [raw]
        if not raw.lower().endswith(".txt"):
            candidates.insert(0, raw + ".txt")

        for candidate in candidates:
            path = os.path.abspath(os.path.join(wildcards_dir, candidate))
            try:
                if os.path.commonpath([os.path.abspath(wildcards_dir), path]) == os.path.abspath(wildcards_dir) and os.path.isfile(path):
                    return path
            except Exception:
                pass

        normalized = raw.lower().removesuffix(".txt")
        normalized_space = normalized.replace("_", " ")
        try:
            for root, dirs, files in os.walk(wildcards_dir):
                for f in files:
                    if not f.lower().endswith(".txt"):
                        continue
                    path = os.path.join(root, f)
                    rel = os.path.relpath(path, wildcards_dir).replace("\\", "/")
                    rel_no_ext = os.path.splitext(rel)[0].lower()
                    base_no_ext = os.path.splitext(f)[0].lower()
                    names = {
                        rel_no_ext,
                        rel_no_ext.replace("_", " "),
                        base_no_ext,
                        base_no_ext.replace("_", " "),
                    }
                    if normalized in names or normalized_space in names:
                        return path
        except Exception:
            return None
        return None

    def _load_lines(self, wildcard_name):
        path = self._find_wildcard_file(wildcard_name)
        if not path:
            return [], ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.read().splitlines() if line.strip()]
            return lines, os.path.relpath(path, self._wildcards_dir()).replace("\\", "/")
        except Exception as e:
            print(f"[Wildcard Text Processor] load failed '{wildcard_name}': {e}")
            return [], ""

    def process(self, text, seed=0, mode="seeded", recursive_depth=5, missing_behavior="keep"):
        rng = random.Random(None if mode == "random" else int(seed))
        used = []

        def pick(name, original):
            lines, rel = self._load_lines(name)
            if not lines:
                print(f"[Wildcard Text Processor] missing wildcard: {name}")
                return original if missing_behavior == "keep" else ""
            idx = rng.randrange(len(lines))
            used.append(f"{rel}:{idx + 1}")
            return lines[idx]

        result = str(text)
        wildcard_pattern = re.compile(r"__([^_\n][^\n]*?)__")
        typed_pattern = re.compile(r"(?<!\S)(?:와카|wildcard)\s+([A-Za-z0-9가-힣_./\\-]+)")

        for _ in range(max(0, int(recursive_depth)) + 1):
            before = result
            result = wildcard_pattern.sub(lambda m: pick(m.group(1), m.group(0)), result)
            result = typed_pattern.sub(lambda m: pick(m.group(1), m.group(0)), result)
            if result == before:
                break

        if used:
            print(f"[Wildcard Text Processor] used: {', '.join(used)}")
        return (result,)


class WildcardBatchController:
    def __init__(self):
        self.iteration_count = 0

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "is_complete": ("BOOLEAN", {"default": False}),
                "max_iterations": ("INT", {"default": 100, "min": 1, "max": 10000}),
            }
        }

    RETURN_TYPES = ("BOOLEAN",)
    RETURN_NAMES = ("continue_batch",)
    FUNCTION = "control"
    CATEGORY = "image/animation"

    def control(self, is_complete, max_iterations):
        self.iteration_count += 1
        should_continue = not is_complete and self.iteration_count < max_iterations
        if is_complete:
            self.iteration_count = 0
        return (should_continue,)


class WildcardMultiFileLoader:
    """
    여러 와일드카드 파일을 순차적으로 사용하는 노드.
    파일1의 모든 줄을 다 쓰면 파일2로 넘어감.
    + Add File / - Remove File 버튼으로 동적 추가/제거.
    """

    @classmethod
    def INPUT_TYPES(cls):
        wildcards_dir = get_wildcards_dir()
        wildcard_files = []
        if os.path.exists(wildcards_dir):
            for root, dirs, files in os.walk(wildcards_dir):
                for f in files:
                    if f.endswith('.txt'):
                        wildcard_files.append(os.path.relpath(os.path.join(root, f), wildcards_dir))
            wildcard_files.sort()
        if not wildcard_files:
            wildcard_files = ["prompts.txt"]

        # 8개 슬롯을 만들되 첫 슬롯만 default, 나머지는 "None" 옵션 추가
        file_options_with_none = ["None"] + wildcard_files

        required = {
            "mode": (["sequential", "random"], {"default": "sequential"}),
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
        }
        # 파일 슬롯은 optional로 (JS에서 동적으로 추가)
        return {
            "required": required,
            "optional": FlexibleOptionalInputType(type=any_type, data={
                "char_1": ("STRING", {"multiline": True, "default": ""}),
                "char_present_1": ("STRING", {"multiline": True, "default": ""}),
                "char_missing_1": ("STRING", {"multiline": True, "default": ""}),
            }),
        }

    RETURN_TYPES = ("STRING", "INT", "INT", "STRING", "STRING")
    RETURN_NAMES = ("wildcard_list", "current_line_count", "seed", "current_file_name", "current_line")
    FUNCTION = "load_files"
    CATEGORY = "image/animation"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # 파일 수정 시간 + enable 상태 - 변화 감지
        wildcards_dir = get_wildcards_dir()
        try:
            mtimes = []
            enables = []
            for k, v in kwargs.items():
                if k.startswith("file_") and isinstance(v, str) and v and v != "None":
                    fp = os.path.join(wildcards_dir, v)
                    if os.path.isfile(fp):
                        mtimes.append(os.path.getmtime(fp))
                elif k.startswith("enable_"):
                    enables.append((k, bool(v)))
            return tuple(mtimes) + tuple(sorted(enables)) + (kwargs.get("seed", 0), kwargs.get("mode", "sequential"))
        except Exception:
            return float("nan")

    def _load_one_file(self, wildcard_file):
        """파일 한 개를 읽어서 줄 리스트로 반환"""
        if not wildcard_file or wildcard_file == "None":
            return []
        try:
            file_path = os.path.join(get_wildcards_dir(), wildcard_file)
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return [w.strip() for w in content.split('\n') if w.strip()]
        except Exception as e:
            print(f"[Wildcard Multi File Loader] '{wildcard_file}' 로드 실패: {e}")
            return []

    def load_files(self, mode="sequential", seed=0, **kwargs):
        # file_ 로 시작하는 키 순서대로 정렬해서 수집
        file_keys = sorted(
            [k for k in kwargs.keys() if k.startswith("file_")],
            key=lambda k: int(k.split("_")[1]) if k.split("_")[1].isdigit() else 999
        )

        # 각 파일의 줄 리스트 + 파일명 수집 (enable=False는 제외)
        all_files = []  # (filename, [lines]) 튜플 리스트
        for key in file_keys:
            wildcard_file = kwargs.get(key, "")
            if not wildcard_file or wildcard_file == "None":
                continue
            # 같은 번호의 enable_N 토글 확인
            idx = key.split("_")[1]
            enable_key = f"enable_{idx}"
            is_enabled = kwargs.get(enable_key, True)
            if not is_enabled:
                print(f"[Wildcard Multi File Loader] '{wildcard_file}' 비활성화됨 (스킵)")
                continue
            lines = self._load_one_file(wildcard_file)
            if lines:
                all_files.append((wildcard_file, lines))

        if not all_files:
            return ("", 0, seed, "", "")

        # 모든 줄을 하나의 리스트로 (파일 경계 추적)
        all_lines = []
        line_to_file = []  # 각 줄이 어느 파일에서 왔는지
        for fname, lines in all_files:
            for line in lines:
                all_lines.append(line)
                line_to_file.append(fname)

        total_lines = len(all_lines)

        # mode 처리
        if mode == "random":
            import random as _rnd
            indices = list(range(total_lines))
            _rnd.seed(seed)
            _rnd.shuffle(indices)
            # 셔플된 순서로 재배열
            all_lines = [all_lines[i] for i in indices]
            line_to_file = [line_to_file[i] for i in indices]
            offset = 0
        else:  # sequential
            offset = seed % total_lines if total_lines > 0 else 0

        # seed에 따라 현재 줄 결정
        current_idx = offset
        current_line = all_lines[current_idx] if total_lines > 0 else ""
        current_file_name = line_to_file[current_idx] if total_lines > 0 else ""
        # 확장자 제거
        current_file_name = os.path.splitext(os.path.basename(current_file_name))[0]

        # sequential 모드일 때 offset 적용한 전체 리스트 반환
        if mode == "sequential" and offset > 0:
            rotated_lines = all_lines[offset:] + all_lines[:offset]
            wildcard_list = '\n'.join(rotated_lines)
        else:
            wildcard_list = '\n'.join(all_lines)

        print(f"[Wildcard Multi File Loader] {len(all_files)}개 파일, 총 {total_lines}줄. 현재: [{current_file_name}] '{current_line[:50]}'")

        return (wildcard_list, total_lines, seed, current_file_name, current_line)


class LoadImageBatchFromDirWithFilename:
    sort_methods = ["None", "Alphabetical (ASC)", "Alphabetical (DESC)", "Numerical (ASC)", "Numerical (DESC)", "Datetime (ASC)", "Datetime (DESC)"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "directory": ("STRING", {"default": ""}),
            },
            "optional": {
                "image_load_cap": ("INT", {"default": 0, "min": 0, "step": 1}),
                "start_index": ("INT", {"default": 0, "min": -1, "max": 0xffffffffffffffff, "step": 1}),
                "load_always": ("BOOLEAN", {"default": False, "label_on": "enabled", "label_off": "disabled"}),
                "include_subfolders": ("BOOLEAN", {"default": False, "label_on": "enabled", "label_off": "disabled"}),
                "sort_method": (cls.sort_methods, {"default": "Numerical (ASC)"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING", "INT")
    RETURN_NAMES = ("IMAGE", "MASK", "filename", "filename_no_ext", "image_count")
    OUTPUT_IS_LIST = (True, True, True, True, False)
    FUNCTION = "load_images"
    CATEGORY = "image"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        if 'load_always' in kwargs and kwargs['load_always']:
            return float("NaN")
        return hash(frozenset(kwargs))

    def natural_key(self, s):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]

    def sort_files(self, items, base_path, method):
        def get_ts(name):
            try:
                return os.path.getmtime(os.path.join(base_path, name))
            except:
                return float('-inf')
        if method == "Alphabetical (ASC)": return sorted(items)
        elif method == "Alphabetical (DESC)": return sorted(items, reverse=True)
        elif method == "Numerical (ASC)": return sorted(items, key=self.natural_key)
        elif method == "Numerical (DESC)": return sorted(items, key=self.natural_key, reverse=True)
        elif method == "Datetime (ASC)": return sorted(items, key=get_ts)
        elif method == "Datetime (DESC)": return sorted(items, key=get_ts, reverse=True)
        else: return items

    def load_images(self, directory, image_load_cap=0, start_index=0, load_always=False, include_subfolders=False, sort_method="Numerical (ASC)"):
        if not os.path.isdir(directory):
            raise FileNotFoundError(f"Directory '{directory}' cannot be found.")

        valid_extensions = ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff']

        # 서브폴더 포함 여부에 따라 파일 수집
        if include_subfolders:
            dir_files = []
            for root, dirs, files in os.walk(directory):
                for f in files:
                    if any(f.lower().endswith(ext) for ext in valid_extensions):
                        rel_path = os.path.relpath(os.path.join(root, f), directory)
                        dir_files.append(rel_path)
        else:
            dir_files = os.listdir(directory)
            dir_files = [f for f in dir_files if any(f.lower().endswith(ext) for ext in valid_extensions)]

        if not dir_files:
            raise FileNotFoundError(f"No image files in directory '{directory}'.")

        dir_files = self.sort_files(dir_files, directory, sort_method)
        dir_files = dir_files[start_index:]

        # LIST 출력: 각 이미지를 개별 텐서로 (해상도 유지)
        images, masks, filenames, filenames_no_ext = [], [], [], []
        limit_images = image_load_cap > 0
        image_count = 0

        for f in dir_files:
            if limit_images and image_count >= image_load_cap:
                break
            image_path = os.path.join(directory, f)
            if not os.path.isfile(image_path):
                continue
            i = Image.open(image_path)
            i = ImageOps.exif_transpose(i)
            image = np.array(i.convert("RGB")).astype(np.float32) / 255.0
            image = torch.from_numpy(image)[None,]  # (1, H, W, C)
            if 'A' in i.getbands():
                mask = 1. - torch.from_numpy(np.array(i.getchannel('A')).astype(np.float32) / 255.0)
                mask = mask.unsqueeze(0)  # (1, H, W)
            else:
                mask = torch.zeros((1, 64, 64), dtype=torch.float32, device="cpu")
            images.append(image)
            masks.append(mask)
            filenames.append(f)
            filenames_no_ext.append(os.path.splitext(f)[0])
            image_count += 1

        if not images:
            raise FileNotFoundError(f"No valid images found in '{directory}'.")

        return (images, masks, filenames, filenames_no_ext, len(images))


class VideoFromFolderLoader:
    """
    폴더에서 영상을 시드값에 맞게 ffmpeg로 로드하는 노드
    """
    video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v', '.mpg', '.mpeg']
    sort_methods = ["Numerical (ASC)", "Numerical (DESC)", "Alphabetical (ASC)", "Alphabetical (DESC)", "Datetime (ASC)", "Datetime (DESC)", "None"]
    path_modes = ["filename", "filename_no_ext", "full_path", "relative_path"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder_path": ("STRING", {"default": ""}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            },
            "optional": {
                "include_subfolders": ("BOOLEAN", {"default": False, "label_on": "enabled", "label_off": "disabled"}),
                "sort_method": (cls.sort_methods, {"default": "Numerical (ASC)"}),
                "path_output_mode": (cls.path_modes, {"default": "filename_no_ext"}),
                "force_fps": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 240.0, "step": 0.1}),
                "frame_load_cap": ("INT", {"default": 0, "min": 0, "max": 100000, "step": 1}),
                "skip_first_frames": ("INT", {"default": 0, "min": 0, "max": 100000, "step": 1}),
                "split_count": ("INT", {"default": 0, "min": 0, "max": 32, "step": 1}),
                "hw_decode": (["auto", "cpu", "cuda", "qsv", "d3d11va"], {"default": "auto"}),
                "output_dtype": (["float32", "float16", "uint8"], {"default": "float32"}),
            }
        }

    # 고정 최대 32개 split 슬롯 - frames_1, audio_1, frames_2, audio_2, ... 번갈아 배치
    # (이유: ComfyUI는 슬롯을 이름이 아닌 인덱스로 매칭하므로, 사용자가 일부만 표시해도 인덱스가 맞아야 함)
    _BASE_TYPES = ("IMAGE", "AUDIO", "STRING", "STRING", "INT", "FLOAT", "INT", "INT")
    _BASE_NAMES = ("frames", "audio", "filename", "full_path", "frame_count", "fps", "width", "height")
    _SPLIT_TYPES = tuple(t for i in range(1, 33) for t in ("IMAGE", "AUDIO"))
    _SPLIT_NAMES = tuple(n for i in range(1, 33) for n in (f"frames_{i}", f"audio_{i}"))
    # parent_folder는 split 슬롯 뒤에 추가 (기존 워크플로우 인덱스 호환 유지)
    RETURN_TYPES = _BASE_TYPES + _SPLIT_TYPES + ("STRING",)
    RETURN_NAMES = _BASE_NAMES + _SPLIT_NAMES + ("parent_folder",)
    FUNCTION = "load_video"
    CATEGORY = "video"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return hash(frozenset(kwargs.items()))

    def natural_key(self, s):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]

    def sort_files(self, items, base_path, method):
        def get_ts(name):
            try:
                return os.path.getmtime(os.path.join(base_path, name))
            except:
                return float('-inf')
        if method == "Alphabetical (ASC)": return sorted(items)
        elif method == "Alphabetical (DESC)": return sorted(items, reverse=True)
        elif method == "Numerical (ASC)": return sorted(items, key=self.natural_key)
        elif method == "Numerical (DESC)": return sorted(items, key=self.natural_key, reverse=True)
        elif method == "Datetime (ASC)": return sorted(items, key=get_ts)
        elif method == "Datetime (DESC)": return sorted(items, key=get_ts, reverse=True)
        else: return items

    def _get_ffmpeg_paths(self):
        """ffmpeg/ffprobe 경로 찾기: 노드 폴더 내 ffmpeg 폴더 우선, 없으면 시스템 PATH"""
        import shutil
        import platform

        node_dir = os.path.dirname(os.path.abspath(__file__))
        ffmpeg_dir = os.path.join(node_dir, "ffmpeg")

        is_windows = platform.system() == "Windows"
        ffmpeg_name = "ffmpeg.exe" if is_windows else "ffmpeg"
        ffprobe_name = "ffprobe.exe" if is_windows else "ffprobe"

        # 1. 노드 폴더 내 ffmpeg/ 안에 있는지 확인 (bin 서브폴더도 체크)
        candidates = [
            os.path.join(ffmpeg_dir, ffmpeg_name),
            os.path.join(ffmpeg_dir, "bin", ffmpeg_name),
        ]
        ffmpeg_path = None
        for c in candidates:
            if os.path.isfile(c):
                ffmpeg_path = c
                break

        candidates = [
            os.path.join(ffmpeg_dir, ffprobe_name),
            os.path.join(ffmpeg_dir, "bin", ffprobe_name),
        ]
        ffprobe_path = None
        for c in candidates:
            if os.path.isfile(c):
                ffprobe_path = c
                break

        # 2. 노드 폴더에 없으면 시스템 PATH에서 찾기
        if not ffmpeg_path:
            ffmpeg_path = shutil.which("ffmpeg")
        if not ffprobe_path:
            ffprobe_path = shutil.which("ffprobe")

        if not ffmpeg_path or not ffprobe_path:
            raise RuntimeError(
                f"ffmpeg/ffprobe를 찾을 수 없습니다.\n"
                f"1) 시스템 PATH에 ffmpeg 설치 또는\n"
                f"2) 노드 폴더 '{ffmpeg_dir}' 또는 '{ffmpeg_dir}/bin'에 ffmpeg.exe, ffprobe.exe 배치"
            )

        print(f"[Video Loader] ffmpeg: {ffmpeg_path}")
        print(f"[Video Loader] ffprobe: {ffprobe_path}")

        return ffmpeg_path, ffprobe_path

    def _run_subprocess(self, cmd, capture=True, timeout=30):
        """Windows에서 콘솔 창 안 뜨게 + 안전하게 실행. timeout 기본 30초 (ffprobe hang 방지)"""
        import subprocess
        import platform

        kwargs = {}
        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = startupinfo
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        if capture:
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.PIPE

        if timeout is not None and timeout > 0:
            kwargs["timeout"] = timeout

        try:
            return subprocess.run(cmd, **kwargs)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"subprocess timeout ({timeout}초 초과): {' '.join(cmd[:5])}...") from e

    def load_video(self, folder_path, seed=0, include_subfolders=False, sort_method="Numerical (ASC)",
                   path_output_mode="filename_no_ext", force_fps=0.0, frame_load_cap=0,
                   skip_first_frames=0, split_count=0, hw_decode="auto", output_dtype="float32"):
        import subprocess
        import json as _json

        # ffmpeg 경로 찾기
        ffmpeg_exe, ffprobe_exe = self._get_ffmpeg_paths()

        if not os.path.isdir(folder_path):
            raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {folder_path}")

        # 영상 파일 수집
        video_files = []
        if include_subfolders:
            for root, dirs, files in os.walk(folder_path):
                for f in files:
                    if any(f.lower().endswith(ext) for ext in self.video_extensions):
                        rel_path = os.path.relpath(os.path.join(root, f), folder_path)
                        video_files.append(rel_path)
        else:
            for f in os.listdir(folder_path):
                fp = os.path.join(folder_path, f)
                if os.path.isfile(fp) and any(f.lower().endswith(ext) for ext in self.video_extensions):
                    video_files.append(f)

        if not video_files:
            raise FileNotFoundError(f"영상 파일이 없습니다: {folder_path}")

        # 정렬
        video_files = self.sort_files(video_files, folder_path, sort_method)

        # seed로 선택
        selected_idx = seed % len(video_files)
        selected_rel = video_files[selected_idx]
        full_path = os.path.join(folder_path, selected_rel)

        print(f"[Video From Folder Loader] seed={seed} → [{selected_idx+1}/{len(video_files)}] {selected_rel}")

        # ffprobe로 영상 정보 가져오기
        probe_cmd = [
            ffprobe_exe, "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", full_path
        ]
        try:
            result = self._run_subprocess(probe_cmd)
            stdout = result.stdout.decode('utf-8', errors='ignore') if result.stdout else ""
            stderr = result.stderr.decode('utf-8', errors='ignore') if result.stderr else ""

            if result.returncode != 0:
                raise RuntimeError(f"ffprobe 실패 (returncode={result.returncode}): {stderr}")
            if not stdout.strip():
                raise RuntimeError(f"ffprobe가 빈 출력 반환. stderr: {stderr}")

            probe_data = _json.loads(stdout)
        except FileNotFoundError as e:
            raise RuntimeError(f"ffprobe 실행파일을 찾을 수 없음 ({ffprobe_exe}): {e}")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"ffprobe 실행 실패: {type(e).__name__}: {e}")

        # 비디오 스트림 찾기
        video_stream = None
        audio_stream = None
        for s in probe_data.get("streams", []):
            if s.get("codec_type") == "video" and video_stream is None:
                video_stream = s
            elif s.get("codec_type") == "audio" and audio_stream is None:
                audio_stream = s

        if video_stream is None:
            raise RuntimeError(f"영상 스트림을 찾을 수 없습니다: {full_path}")

        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))

        # FPS 계산
        fps_str = video_stream.get("r_frame_rate", "0/1")
        try:
            num, den = fps_str.split("/")
            orig_fps = float(num) / float(den) if float(den) > 0 else 0.0
        except:
            orig_fps = 0.0

        target_fps = force_fps if force_fps > 0 else orig_fps

        # 예상 프레임 수 계산 (ProgressBar용)
        nb_frames_str = video_stream.get("nb_frames", "0")
        try:
            total_video_frames = int(nb_frames_str) if nb_frames_str.isdigit() else 0
        except:
            total_video_frames = 0
        # nb_frames 없으면 duration * fps로 추정
        if total_video_frames == 0:
            try:
                duration = float(probe_data.get("format", {}).get("duration", 0))
                total_video_frames = int(duration * orig_fps) if orig_fps > 0 else 0
            except:
                total_video_frames = 0

        # skip + cap 적용해서 실제 추출될 프레임 수 추정
        expected_frames = max(0, total_video_frames - skip_first_frames)
        if force_fps > 0 and orig_fps > 0:
            expected_frames = int(expected_frames * (force_fps / orig_fps))
        if frame_load_cap > 0:
            expected_frames = min(expected_frames, frame_load_cap)

        # ffmpeg 명령어 구성 (GPU 디코딩 지원)
        # hw_decode: "auto" (cuda 시도→실패 시 cpu), "cpu", "cuda", "qsv", "d3d11va"
        def _build_ffmpeg_cmd(hwaccel_mode):
            cmd = [ffmpeg_exe, "-v", "error"]
            if hwaccel_mode == "cuda":
                # CUDA 디코딩: GPU에서 디코딩 후 CPU로 다운로드
                cmd += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
            elif hwaccel_mode == "qsv":
                cmd += ["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"]
            elif hwaccel_mode == "d3d11va":
                cmd += ["-hwaccel", "d3d11va"]
            # cpu면 hwaccel 옵션 없음
            cmd += ["-i", full_path]

            local_vf = []
            if hwaccel_mode in ("cuda", "qsv"):
                # GPU 메모리에서 CPU로 다운로드 + nv12→rgb24 변환은 hwdownload+format으로
                local_vf.append("hwdownload")
                local_vf.append("format=nv12")
            if skip_first_frames > 0:
                local_vf.append(f"select='gte(n,{skip_first_frames})'")
                local_vf.append("setpts=PTS-STARTPTS")
            if force_fps > 0:
                local_vf.append(f"fps={force_fps}")
            if local_vf:
                cmd += ["-vf", ",".join(local_vf)]
            if frame_load_cap > 0:
                cmd += ["-frames:v", str(frame_load_cap)]
            cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
            return cmd

        # hw_decode 모드 결정
        if hw_decode == "auto":
            # auto: cuda 먼저 시도, 실패 시 cpu fallback
            tried_modes = ["cuda", "cpu"]
        else:
            tried_modes = [hw_decode]

        ffmpeg_cmd = _build_ffmpeg_cmd(tried_modes[0])

        # ProgressBar 준비
        try:
            from comfy.utils import ProgressBar
            pbar = ProgressBar(expected_frames) if expected_frames > 0 else None
        except Exception:
            pbar = None

        # ffmpeg 추출 함수 - 실패 시 fallback 가능하게 함수로 분리
        frame_size = width * height * 3
        import threading
        from collections import deque
        import subprocess as _sp
        import platform as _pf

        def _do_extract(cmd):
            """cmd로 ffmpeg 실행, (frames_np, num_frames, stderr_text) 반환. 실패 시 raise"""
            popen_kw = {"stdout": _sp.PIPE, "stderr": _sp.PIPE, "bufsize": 1024 * 1024 * 8}
            if _pf.system() == "Windows":
                si = _sp.STARTUPINFO()
                si.dwFlags |= _sp.STARTF_USESHOWWINDOW
                popen_kw["startupinfo"] = si

            proc = _sp.Popen(cmd, **popen_kw)

            stderr_buf = deque(maxlen=200)
            def _drain(pipe, buf):
                try:
                    for line in iter(pipe.readline, b''):
                        if not line:
                            break
                        buf.append(line.decode('utf-8', errors='ignore').rstrip())
                except Exception:
                    pass
            stderr_thread = threading.Thread(target=_drain, args=(proc.stderr, stderr_buf), daemon=True)
            stderr_thread.start()

            if expected_frames > 0:
                _frames_np = np.empty((expected_frames, height, width, 3), dtype=np.uint8)
                idx = 0
                READ_BATCH = max(1, min(16, expected_frames, max(1, (4 * 1024 * 1024) // frame_size)))
                read_size = frame_size * READ_BATCH
                while idx < expected_frames:
                    data = proc.stdout.read(read_size)
                    if not data:
                        break
                    n_recv = len(data) // frame_size
                    if n_recv == 0:
                        break
                    arr = np.frombuffer(data, dtype=np.uint8, count=n_recv * frame_size).reshape((n_recv, height, width, 3))
                    end = min(idx + n_recv, expected_frames)
                    _frames_np[idx:end] = arr[:end - idx]
                    if pbar is not None:
                        pbar.update(end - idx)
                    idx = end
                _num = idx
                if _num < expected_frames:
                    _frames_np = _frames_np[:_num]
            else:
                chunks = []
                READ_BATCH = max(1, (4 * 1024 * 1024) // frame_size)
                read_size = frame_size * READ_BATCH
                while True:
                    data = proc.stdout.read(read_size)
                    if not data:
                        break
                    n_recv = len(data) // frame_size
                    if n_recv == 0:
                        break
                    arr = np.frombuffer(data, dtype=np.uint8, count=n_recv * frame_size).reshape((n_recv, height, width, 3)).copy()
                    chunks.append(arr)
                    if pbar is not None:
                        pbar.update(n_recv)
                if chunks:
                    _frames_np = np.concatenate(chunks, axis=0)
                else:
                    _frames_np = np.empty((0, height, width, 3), dtype=np.uint8)
                _num = _frames_np.shape[0]

            proc.wait()
            stderr_thread.join(timeout=2.0)

            stderr_text = "\n".join(list(stderr_buf)[-30:])
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg 실행 실패 (returncode={proc.returncode}):\n{stderr_text}")
            return _frames_np, _num, stderr_text

        # 모드 순회하며 시도
        frames_np = None
        num_frames = 0
        last_err = None
        for try_idx, mode in enumerate(tried_modes):
            try:
                cmd_try = _build_ffmpeg_cmd(mode)
                import time as _time
                _t_decode_start = _time.time()
                print(f"[Video Loader] ffmpeg 디코딩 시도: {mode}")
                # ProgressBar 매 시도마다 재설정 (이전 시도 실패해도 깨끗하게)
                try:
                    from comfy.utils import ProgressBar
                    if expected_frames > 0:
                        pbar = ProgressBar(expected_frames)
                except Exception:
                    pass
                frames_np, num_frames, _ = _do_extract(cmd_try)
                if num_frames > 0:
                    print(f"[Video Loader] ✅ {mode} 디코딩 성공: {num_frames}프레임 ({_time.time()-_t_decode_start:.1f}초)")
                    break
                last_err = f"{mode}: 프레임 0개"
            except FileNotFoundError as e:
                raise RuntimeError(f"ffmpeg 실행파일을 찾을 수 없음 ({ffmpeg_exe}): {e}")
            except Exception as e:
                last_err = str(e)
                print(f"[Video Loader] ⚠️ {mode} 실패: {str(e)[:200]}")
                if try_idx < len(tried_modes) - 1:
                    print(f"[Video Loader] → {tried_modes[try_idx+1]}로 fallback")
                continue

        if not num_frames or frames_np is None:
            raise RuntimeError(f"모든 디코딩 모드 실패. 마지막 에러:\n{last_err}")

        _t_conv_start = _time.time() if '_time' in dir() else None
        # uint8 → float32 변환은 메모리 4배라 매우 느림 (4K 영상이면 수 GB)
        # 청크 단위로 변환해서 메모리 압박 줄이고 진행률 표시
        try:
            from comfy.utils import ProgressBar as _PB
            _conv_pbar = _PB(num_frames)
        except Exception:
            _conv_pbar = None

        # output_dtype 따라 변환 방식 결정
        # - uint8: 변환 안 함 (가장 빠름, 일부 노드 호환 안 될 수 있음)
        # - float16: 절반 메모리, CPU에서 변환 빠름 (대부분 노드 호환)
        # - float32: ComfyUI 표준 (가장 호환적, 가장 느림)
        _gpu_available = False
        try:
            _gpu_available = torch.cuda.is_available()
        except Exception:
            pass

        if output_dtype == "uint8":
            # 변환 없음 - 가장 빠름, 위험
            frames_tensor = torch.from_numpy(frames_np)
            if _conv_pbar is not None:
                _conv_pbar.update(num_frames)
        elif output_dtype == "float16":
            # float16 - 메모리 절반, 빠름
            target_dtype = torch.float16
            if num_frames > 50:
                frames_tensor = torch.empty((num_frames, height, width, 3), dtype=target_dtype)
                CHUNK = 64
                for i in range(0, num_frames, CHUNK):
                    end = min(i + CHUNK, num_frames)
                    if _gpu_available:
                        chunk_uint8 = torch.from_numpy(frames_np[i:end]).cuda(non_blocking=True)
                        frames_tensor[i:end] = (chunk_uint8.to(target_dtype) / 255.0).cpu()
                        del chunk_uint8
                    else:
                        frames_tensor[i:end] = torch.from_numpy(frames_np[i:end]).to(target_dtype).div_(255.0)
                    if _conv_pbar is not None:
                        _conv_pbar.update(end - i)
                del frames_np
                if _gpu_available:
                    torch.cuda.empty_cache()
            else:
                if _gpu_available:
                    frames_tensor = (torch.from_numpy(frames_np).cuda().to(target_dtype) / 255.0).cpu()
                else:
                    frames_tensor = torch.from_numpy(frames_np).to(target_dtype) / 255.0
        else:
            # float32 (기본) - 표준, 가장 느림
            if num_frames > 50:
                frames_tensor = torch.empty((num_frames, height, width, 3), dtype=torch.float32)
                CHUNK = 32
                for i in range(0, num_frames, CHUNK):
                    end = min(i + CHUNK, num_frames)
                    if _gpu_available:
                        chunk_uint8 = torch.from_numpy(frames_np[i:end]).cuda(non_blocking=True)
                        frames_tensor[i:end] = (chunk_uint8.float() / 255.0).cpu()
                        del chunk_uint8
                    else:
                        frames_tensor[i:end] = torch.from_numpy(frames_np[i:end]).float().div_(255.0)
                    if _conv_pbar is not None:
                        _conv_pbar.update(end - i)
                del frames_np
                if _gpu_available:
                    torch.cuda.empty_cache()
            else:
                if _gpu_available:
                    frames_tensor = (torch.from_numpy(frames_np).cuda().float() / 255.0).cpu()
                else:
                    frames_tensor = torch.from_numpy(frames_np).float() / 255.0

        if _t_conv_start is not None:
            print(f"[Video Loader] float32 변환 완료 ({_time.time()-_t_conv_start:.1f}초, {num_frames}프레임)")

        # 오디오 로드 - 무조건 시도 (실패해도 빈 오디오 반환)
        audio_output = {"waveform": torch.zeros((1, 2, 1)), "sample_rate": 44100}
        try:
            import subprocess as _sp
            import platform as _pf
            audio_cmd = [ffmpeg_exe, "-i", full_path, "-vn", "-f", "f32le", "-"]

            # Windows에서 콘솔창 안 뜨게
            kw = {"capture_output": True}
            if _pf.system() == "Windows":
                si = _sp.STARTUPINFO()
                si.dwFlags |= _sp.STARTF_USESHOWWINDOW
                kw["startupinfo"] = si

            audio_proc = _sp.run(audio_cmd, **kw)
            audio_raw = audio_proc.stdout if audio_proc.stdout else b""
            audio_stderr = audio_proc.stderr.decode('utf-8', errors='backslashreplace') if audio_proc.stderr else ""

            if len(audio_raw) > 0:
                audio_tensor = torch.frombuffer(bytearray(audio_raw), dtype=torch.float32)

                # stderr에서 샘플레이트와 채널 정보 파싱
                match = re.search(r', (\d+) Hz, (\w+), ', audio_stderr)
                if match:
                    ar = int(match.group(1))
                    ac = {"mono": 1, "stereo": 2}.get(match.group(2), 2)
                else:
                    ar = 44100
                    ac = 2

                audio_tensor = audio_tensor.reshape((-1, ac)).transpose(0, 1).unsqueeze(0)
                audio_output = {"waveform": audio_tensor, "sample_rate": ar}
                print(f"[Video Loader] 오디오 로드 완료: {ar}Hz, {ac}ch, {audio_tensor.shape[2]} samples")
        except Exception as e:
            print(f"[Video Loader] 오디오 로드 실패: {e}")

        # 경로 출력 모드
        filename_only = os.path.basename(selected_rel)
        if path_output_mode == "filename":
            filename_out = filename_only
        elif path_output_mode == "filename_no_ext":
            filename_out = os.path.splitext(filename_only)[0]
        elif path_output_mode == "full_path":
            filename_out = os.path.abspath(full_path)
        elif path_output_mode == "relative_path":
            filename_out = selected_rel
        else:
            filename_out = filename_only

        print(f"[Video From Folder Loader] 로드 완료: {num_frames}프레임, {width}x{height}, fps={target_fps:.2f}")

        # split_count 처리: 프레임을 N등분 + 오디오도 같이 분할
        split_frames = []
        split_audios = []
        if split_count > 0 and num_frames > 0:
            base_size = num_frames // split_count
            remainder = num_frames % split_count

            # 오디오 분할용 정보
            audio_wf = audio_output.get("waveform")
            audio_sr = audio_output.get("sample_rate", 44100)
            has_real_audio = (audio_wf is not None and audio_wf.numel() > 2)  # 더미(0벡터) 아니면
            total_audio_samples = audio_wf.shape[-1] if has_real_audio else 0

            start_frame = 0
            for i in range(split_count):
                # 프레임 분할
                chunk_size = base_size + (remainder if i == split_count - 1 else 0)
                if chunk_size <= 0:
                    split_frames.append(frames_tensor[:1].clone())
                    # 빈 오디오
                    split_audios.append({"waveform": torch.zeros((1, 2, 1)), "sample_rate": audio_sr})
                    continue
                end_frame = start_frame + chunk_size
                split_frames.append(frames_tensor[start_frame:end_frame])

                # 오디오 분할: 해당 프레임 범위에 대응하는 샘플 범위
                if has_real_audio and target_fps > 0:
                    # 프레임 인덱스를 시간으로 변환 후 샘플 인덱스로
                    audio_start = int((start_frame / target_fps) * audio_sr)
                    audio_end = int((end_frame / target_fps) * audio_sr)
                    audio_start = max(0, min(audio_start, total_audio_samples))
                    audio_end = max(audio_start, min(audio_end, total_audio_samples))
                    # 마지막 청크는 남은 오디오 다 가져가기
                    if i == split_count - 1:
                        audio_end = total_audio_samples
                    chunk_audio = audio_wf[:, :, audio_start:audio_end].clone()
                    split_audios.append({"waveform": chunk_audio, "sample_rate": audio_sr})
                else:
                    # 오디오 없으면 빈 오디오
                    split_audios.append({"waveform": torch.zeros((1, 2, 1)), "sample_rate": audio_sr})

                start_frame = end_frame
            print(f"[Video Loader] {num_frames}프레임을 {split_count}등분 (마지막 청크에 나머지 {remainder} 추가)")
            if has_real_audio:
                print(f"[Video Loader] 오디오도 {split_count}등분")

        # 출력: 기본 8개 + (frames_i, audio_i) * 32 (번갈아 배치)
        # RETURN_TYPES와 정확히 일치해야 인덱스 매칭이 어긋나지 않음
        MAX_SLOTS = 32
        dummy_frame = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
        dummy_audio = {"waveform": torch.zeros((1, 2, 1)), "sample_rate": 44100}

        result = (frames_tensor, audio_output, filename_out, os.path.abspath(full_path), num_frames, target_fps, width, height)
        # (frames_i, audio_i) 쌍을 번갈아 추가
        for i in range(MAX_SLOTS):
            if i < len(split_frames):
                result += (split_frames[i],)
            else:
                result += (dummy_frame,)
            if i < len(split_audios):
                result += (split_audios[i],)
            else:
                result += (dummy_audio,)

        # parent_folder (영상이 들어있는 폴더 이름, 전체 경로 아닌)
        parent_folder_name = os.path.basename(os.path.dirname(os.path.abspath(full_path)))
        result += (parent_folder_name,)

        return result


class VideoFromFolderLoaderSimple:
    """
    VideoFromFolderLoader의 간단한 버전 - split 기능 없이 영상 1개만 로드.
    노드가 너무 길어지지 않게 split이 필요 없는 워크플로우용.
    """
    sort_methods = ["Numerical (ASC)", "Numerical (DESC)", "Alphabetical (ASC)", "Alphabetical (DESC)", "Datetime (ASC)", "Datetime (DESC)", "Random"]
    path_output_modes = ["filename_no_ext", "filename_with_ext", "full_path", "relative_path"]
    video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v']

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder_path": ("STRING", {"default": ""}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "include_subfolders": ("BOOLEAN", {"default": False}),
                "sort_method": (cls.sort_methods, {"default": "Numerical (ASC)"}),
                "path_output_mode": (cls.path_output_modes, {"default": "filename_no_ext"}),
                "force_fps": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 240.0, "step": 0.01}),
                "frame_load_cap": ("INT", {"default": 0, "min": 0, "max": 100000, "step": 1}),
                "skip_first_frames": ("INT", {"default": 0, "min": 0, "max": 100000, "step": 1}),
                "hw_decode": (["auto", "cpu", "cuda", "qsv", "d3d11va"], {"default": "auto"}),
                "output_dtype": (["float32", "float16", "uint8"], {"default": "float32"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "AUDIO", "STRING", "STRING", "STRING", "INT", "FLOAT", "INT", "INT", "IMAGE", "IMAGE")
    RETURN_NAMES = ("frames", "audio", "filename", "full_path", "parent_folder", "frame_count", "fps", "width", "height", "first_frame", "last_frame")
    FUNCTION = "load_video"
    CATEGORY = "video"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")  # 항상 실행

    def _get_ffmpeg_paths(self):
        return VideoFromFolderLoader._get_ffmpeg_paths(self)

    def _run_subprocess(self, cmd, capture=True):
        return VideoFromFolderLoader._run_subprocess(self, cmd, capture)

    def natural_key(self, s):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]

    def sort_files(self, items, base_path, method, seed=0):
        def get_ts(name):
            try:
                return os.path.getmtime(os.path.join(base_path, name))
            except:
                return float('-inf')
        if method == "Alphabetical (ASC)": return sorted(items)
        elif method == "Alphabetical (DESC)": return sorted(items, reverse=True)
        elif method == "Numerical (ASC)": return sorted(items, key=self.natural_key)
        elif method == "Numerical (DESC)": return sorted(items, key=self.natural_key, reverse=True)
        elif method == "Datetime (ASC)": return sorted(items, key=get_ts)
        elif method == "Datetime (DESC)": return sorted(items, key=get_ts, reverse=True)
        elif method == "Random":
            r = random.Random(seed)
            items_copy = list(items)
            r.shuffle(items_copy)
            return items_copy
        else: return items

    def load_video(self, folder_path, seed=0, include_subfolders=False, sort_method="Numerical (ASC)",
                   path_output_mode="filename_no_ext", force_fps=0.0, frame_load_cap=0,
                   skip_first_frames=0, hw_decode="auto", output_dtype="float32", exact_path=None):
        import json as _json

        ffmpeg_exe, ffprobe_exe = self._get_ffmpeg_paths()

        if exact_path:
            full_path = os.path.abspath(str(exact_path))
            if not os.path.isfile(full_path):
                raise FileNotFoundError(f"영상 파일을 찾을 수 없습니다: {full_path}")
            folder_path = os.path.dirname(full_path)
            chosen = os.path.basename(full_path)
            video_files = [chosen]
            idx = 0
        else:
            if not os.path.isdir(folder_path):
                raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {folder_path}")

            # 영상 파일 수집
            video_files = []
            if include_subfolders:
                for root, dirs, files in os.walk(folder_path):
                    for f in files:
                        if any(f.lower().endswith(ext) for ext in self.video_extensions):
                            rel = os.path.relpath(os.path.join(root, f), folder_path)
                            video_files.append(rel)
            else:
                for f in os.listdir(folder_path):
                    if any(f.lower().endswith(ext) for ext in self.video_extensions):
                        video_files.append(f)

            if not video_files:
                raise RuntimeError(f"영상 파일이 없습니다: {folder_path}")

            video_files = self.sort_files(video_files, folder_path, sort_method, seed)
            idx = seed % len(video_files)
            chosen = video_files[idx]
            full_path = os.path.join(folder_path, chosen)

        print(f"[Video Loader Simple] 선택: [{idx+1}/{len(video_files)}] {chosen}")

        # filename 출력
        if path_output_mode == "filename_no_ext":
            filename_out = os.path.splitext(os.path.basename(chosen))[0]
        elif path_output_mode == "filename_with_ext":
            filename_out = os.path.basename(chosen)
        elif path_output_mode == "full_path":
            filename_out = os.path.abspath(full_path)
        else:  # relative_path
            filename_out = chosen

        # ffprobe
        probe_cmd = [ffprobe_exe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", full_path]
        try:
            result = self._run_subprocess(probe_cmd)
            stdout = result.stdout.decode('utf-8', errors='ignore') if result.stdout else ""
            stderr = result.stderr.decode('utf-8', errors='ignore') if result.stderr else ""
            if result.returncode != 0:
                raise RuntimeError(f"ffprobe 실패 (returncode={result.returncode}): {stderr}")
            if not stdout.strip():
                raise RuntimeError(f"ffprobe가 빈 출력 반환. stderr: {stderr}")
            probe_data = _json.loads(stdout)
        except FileNotFoundError as e:
            raise RuntimeError(f"ffprobe 실행파일을 찾을 수 없음: {e}")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"ffprobe 실행 실패: {type(e).__name__}: {e}")

        video_stream = None
        audio_stream = None
        for s in probe_data.get("streams", []):
            if s.get("codec_type") == "video" and video_stream is None:
                video_stream = s
            elif s.get("codec_type") == "audio" and audio_stream is None:
                audio_stream = s

        if video_stream is None:
            raise RuntimeError(f"영상 스트림을 찾을 수 없습니다: {full_path}")

        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))

        fps_str = video_stream.get("r_frame_rate", "0/1")
        try:
            num, den = fps_str.split("/")
            orig_fps = float(num) / float(den) if float(den) > 0 else 0.0
        except:
            orig_fps = 0.0
        target_fps = force_fps if force_fps > 0 else orig_fps

        # 예상 프레임 수 (ProgressBar용)
        nb_frames_str = video_stream.get("nb_frames", "0")
        try:
            total_video_frames = int(nb_frames_str) if nb_frames_str.isdigit() else 0
        except:
            total_video_frames = 0
        if total_video_frames == 0:
            try:
                duration = float(probe_data.get("format", {}).get("duration", 0))
                total_video_frames = int(duration * orig_fps) if orig_fps > 0 else 0
            except:
                total_video_frames = 0

        expected_frames = max(0, total_video_frames - skip_first_frames)
        if force_fps > 0 and orig_fps > 0:
            expected_frames = int(expected_frames * (force_fps / orig_fps))
        if frame_load_cap > 0:
            expected_frames = min(expected_frames, frame_load_cap)

        # ffmpeg 명령 (GPU 디코딩 지원)
        def _build_ffmpeg_cmd(hwaccel_mode):
            cmd = [ffmpeg_exe, "-v", "error"]
            if hwaccel_mode == "cuda":
                cmd += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
            elif hwaccel_mode == "qsv":
                cmd += ["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"]
            elif hwaccel_mode == "d3d11va":
                cmd += ["-hwaccel", "d3d11va"]
            cmd += ["-i", full_path]
            local_vf = []
            if hwaccel_mode in ("cuda", "qsv"):
                local_vf.append("hwdownload")
                local_vf.append("format=nv12")
            if skip_first_frames > 0:
                local_vf.append(f"select='gte(n,{skip_first_frames})'")
                local_vf.append("setpts=PTS-STARTPTS")
            if force_fps > 0:
                local_vf.append(f"fps={force_fps}")
            if local_vf:
                cmd += ["-vf", ",".join(local_vf)]
            if frame_load_cap > 0:
                cmd += ["-frames:v", str(frame_load_cap)]
            cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
            return cmd

        if hw_decode == "auto":
            tried_modes = ["cuda", "cpu"]
        else:
            tried_modes = [hw_decode]

        ffmpeg_cmd = _build_ffmpeg_cmd(tried_modes[0])

        # ProgressBar
        try:
            from comfy.utils import ProgressBar
            pbar = ProgressBar(expected_frames) if expected_frames > 0 else None
        except Exception:
            pbar = None

        # ffmpeg 추출 - fallback 지원
        frame_size = width * height * 3
        import threading
        from collections import deque
        import subprocess as _sp
        import platform as _pf

        # hang 감지용 타임아웃 (초)
        INIT_TIMEOUT = 30.0   # ffmpeg 첫 프레임 출력까지 (시크/초기화)
        STALL_TIMEOUT = 60.0  # 첫 프레임 이후 새 데이터 없을 때

        def _do_extract(cmd):
            import time as _t
            popen_kw = {"stdout": _sp.PIPE, "stderr": _sp.PIPE, "bufsize": 1024 * 1024 * 8}
            if _pf.system() == "Windows":
                si = _sp.STARTUPINFO()
                si.dwFlags |= _sp.STARTF_USESHOWWINDOW
                popen_kw["startupinfo"] = si
            proc = _sp.Popen(cmd, **popen_kw)
            stderr_buf = deque(maxlen=200)

            # watchdog 상태
            last_data_time = [_t.time()]
            first_data_received = [False]
            aborted = [False]
            abort_reason = [""]

            def _watchdog():
                while proc.poll() is None and not aborted[0]:
                    now = _t.time()
                    since_last = now - last_data_time[0]
                    timeout_to_use = INIT_TIMEOUT if not first_data_received[0] else STALL_TIMEOUT
                    if since_last > timeout_to_use:
                        phase = "초기화/시크" if not first_data_received[0] else "스트리밍"
                        abort_reason[0] = f"ffmpeg {phase} 단계에서 {timeout_to_use:.0f}초 응답 없음 (hang으로 판단)"
                        print(f"[Video Loader Simple] ⏰ {abort_reason[0]} → 강제 종료")
                        stderr_snapshot = "\n".join(list(stderr_buf)[-20:])
                        if stderr_snapshot.strip():
                            print(f"[Video Loader Simple] 강제 종료 시점 stderr:\n{stderr_snapshot}")
                        else:
                            print(f"[Video Loader Simple] stderr 출력 없음 (ffmpeg가 아무것도 안 찍는 상태)")
                        aborted[0] = True
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        break
                    _t.sleep(2.0)

            watchdog_thread = threading.Thread(target=_watchdog, daemon=True)
            watchdog_thread.start()

            def _drain(pipe, buf):
                try:
                    for line in iter(pipe.readline, b''):
                        if not line:
                            break
                        buf.append(line.decode('utf-8', errors='ignore').rstrip())
                except Exception:
                    pass
            stderr_thread = threading.Thread(target=_drain, args=(proc.stderr, stderr_buf), daemon=True)
            stderr_thread.start()

            def _mark_data():
                if not first_data_received[0]:
                    first_data_received[0] = True
                    print(f"[Video Loader Simple] ▶ 첫 프레임 수신")
                last_data_time[0] = _t.time()

            if expected_frames > 0:
                _frames_np = np.empty((expected_frames, height, width, 3), dtype=np.uint8)
                idx = 0
                READ_BATCH = max(1, min(16, expected_frames, max(1, (4 * 1024 * 1024) // frame_size)))
                read_size = frame_size * READ_BATCH
                while idx < expected_frames:
                    data = proc.stdout.read(read_size)
                    if not data:
                        break
                    _mark_data()
                    n_recv = len(data) // frame_size
                    if n_recv == 0:
                        break
                    arr = np.frombuffer(data, dtype=np.uint8, count=n_recv * frame_size).reshape((n_recv, height, width, 3))
                    end = min(idx + n_recv, expected_frames)
                    _frames_np[idx:end] = arr[:end - idx]
                    if pbar is not None:
                        pbar.update(end - idx)
                    idx = end
                _num = idx
                if _num < expected_frames:
                    _frames_np = _frames_np[:_num]
            else:
                chunks = []
                READ_BATCH = max(1, (4 * 1024 * 1024) // frame_size)
                read_size = frame_size * READ_BATCH
                while True:
                    data = proc.stdout.read(read_size)
                    if not data:
                        break
                    _mark_data()
                    n_recv = len(data) // frame_size
                    if n_recv == 0:
                        break
                    arr = np.frombuffer(data, dtype=np.uint8, count=n_recv * frame_size).reshape((n_recv, height, width, 3)).copy()
                    chunks.append(arr)
                    if pbar is not None:
                        pbar.update(n_recv)
                if chunks:
                    _frames_np = np.concatenate(chunks, axis=0)
                else:
                    _frames_np = np.empty((0, height, width, 3), dtype=np.uint8)
                _num = _frames_np.shape[0]
            try:
                proc.wait(timeout=10.0)
            except _sp.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                proc.wait()
            stderr_thread.join(timeout=2.0)
            stderr_text = "\n".join(list(stderr_buf)[-30:])
            if aborted[0]:
                raise RuntimeError(
                    f"{abort_reason[0]}\n"
                    f"--- 실행 명령 ---\n{' '.join(cmd)}\n"
                    f"--- 최근 stderr ---\n{stderr_text if stderr_text.strip() else '(없음)'}"
                )
            if proc.returncode != 0:
                # broken pipe 케이스 관용: 데이터 정상 수신 + stderr 비어있으면 성공 처리
                if _num > 0 and not stderr_text.strip():
                    print(f"[Video Loader Simple] ⚠️ ffmpeg returncode={proc.returncode} + stderr 비어있음 + {_num}프레임 수신 → broken pipe 추정, 성공 처리")
                else:
                    raise RuntimeError(f"ffmpeg 실행 실패 (returncode={proc.returncode}):\n{stderr_text}")
            return _frames_np, _num

        frames_np = None
        num_frames = 0
        last_err = None
        for try_idx, mode in enumerate(tried_modes):
            try:
                cmd_try = _build_ffmpeg_cmd(mode)
                import time as _time
                _t_decode_start = _time.time()
                print(f"[Video Loader Simple] ffmpeg 디코딩 시도: {mode}")
                print(f"[Video Loader Simple] 명령: {' '.join(cmd_try)}")
                try:
                    from comfy.utils import ProgressBar
                    if expected_frames > 0:
                        pbar = ProgressBar(expected_frames)
                except Exception:
                    pass
                frames_np, num_frames = _do_extract(cmd_try)
                if num_frames > 0:
                    print(f"[Video Loader Simple] ✅ {mode} 성공: {num_frames}프레임 ({_time.time()-_t_decode_start:.1f}초)")
                    break
                last_err = f"{mode}: 프레임 0개"
            except FileNotFoundError as e:
                raise RuntimeError(f"ffmpeg 실행파일을 찾을 수 없음: {e}")
            except Exception as e:
                last_err = str(e)
                print(f"[Video Loader Simple] ⚠️ {mode} 실패: {str(e)[:300]}")
                if try_idx < len(tried_modes) - 1:
                    print(f"[Video Loader Simple] → {tried_modes[try_idx+1]}로 fallback")
                continue

        if not num_frames or frames_np is None:
            raise RuntimeError(f"모든 디코딩 모드 실패. 마지막 에러:\n{last_err}")

        _t_conv_start = _time.time() if '_time' in dir() else None
        # uint8 → float32 변환은 메모리 4배라 매우 느림 (4K 영상이면 수 GB)
        # 청크 단위로 변환해서 메모리 압박 줄이고 진행률 표시
        try:
            from comfy.utils import ProgressBar as _PB
            _conv_pbar = _PB(num_frames)
        except Exception:
            _conv_pbar = None

        # output_dtype 따라 변환 방식 결정
        # - uint8: 변환 안 함 (가장 빠름, 일부 노드 호환 안 될 수 있음)
        # - float16: 절반 메모리, CPU에서 변환 빠름 (대부분 노드 호환)
        # - float32: ComfyUI 표준 (가장 호환적, 가장 느림)
        _gpu_available = False
        try:
            _gpu_available = torch.cuda.is_available()
        except Exception:
            pass

        if output_dtype == "uint8":
            # 변환 없음 - 가장 빠름, 위험
            frames_tensor = torch.from_numpy(frames_np)
            if _conv_pbar is not None:
                _conv_pbar.update(num_frames)
        elif output_dtype == "float16":
            # float16 - 메모리 절반, 빠름
            target_dtype = torch.float16
            if num_frames > 50:
                frames_tensor = torch.empty((num_frames, height, width, 3), dtype=target_dtype)
                CHUNK = 64
                for i in range(0, num_frames, CHUNK):
                    end = min(i + CHUNK, num_frames)
                    if _gpu_available:
                        chunk_uint8 = torch.from_numpy(frames_np[i:end]).cuda(non_blocking=True)
                        frames_tensor[i:end] = (chunk_uint8.to(target_dtype) / 255.0).cpu()
                        del chunk_uint8
                    else:
                        frames_tensor[i:end] = torch.from_numpy(frames_np[i:end]).to(target_dtype).div_(255.0)
                    if _conv_pbar is not None:
                        _conv_pbar.update(end - i)
                del frames_np
                if _gpu_available:
                    torch.cuda.empty_cache()
            else:
                if _gpu_available:
                    frames_tensor = (torch.from_numpy(frames_np).cuda().to(target_dtype) / 255.0).cpu()
                else:
                    frames_tensor = torch.from_numpy(frames_np).to(target_dtype) / 255.0
        else:
            # float32 (기본) - 표준, 가장 느림
            if num_frames > 50:
                frames_tensor = torch.empty((num_frames, height, width, 3), dtype=torch.float32)
                CHUNK = 32
                for i in range(0, num_frames, CHUNK):
                    end = min(i + CHUNK, num_frames)
                    if _gpu_available:
                        chunk_uint8 = torch.from_numpy(frames_np[i:end]).cuda(non_blocking=True)
                        frames_tensor[i:end] = (chunk_uint8.float() / 255.0).cpu()
                        del chunk_uint8
                    else:
                        frames_tensor[i:end] = torch.from_numpy(frames_np[i:end]).float().div_(255.0)
                    if _conv_pbar is not None:
                        _conv_pbar.update(end - i)
                del frames_np
                if _gpu_available:
                    torch.cuda.empty_cache()
            else:
                if _gpu_available:
                    frames_tensor = (torch.from_numpy(frames_np).cuda().float() / 255.0).cpu()
                else:
                    frames_tensor = torch.from_numpy(frames_np).float() / 255.0

        if _t_conv_start is not None:
            print(f"[Video Loader] float32 변환 완료 ({_time.time()-_t_conv_start:.1f}초, {num_frames}프레임)")

        # 오디오 로드 (60초 timeout)
        audio_output = {"waveform": torch.zeros((1, 2, 1)), "sample_rate": 44100}
        try:
            import subprocess as _sp
            import platform as _pf
            audio_cmd = [ffmpeg_exe, "-i", full_path, "-vn", "-f", "f32le", "-"]
            kw = {"capture_output": True, "timeout": 60}
            if _pf.system() == "Windows":
                si = _sp.STARTUPINFO()
                si.dwFlags |= _sp.STARTF_USESHOWWINDOW
                kw["startupinfo"] = si
            try:
                audio_proc = _sp.run(audio_cmd, **kw)
            except _sp.TimeoutExpired:
                print(f"[Video Loader Simple] ⚠️ 오디오 추출 60초 timeout - 스킵")
                audio_proc = None
            if audio_proc is not None:
                audio_raw = audio_proc.stdout if audio_proc.stdout else b""
                audio_stderr = audio_proc.stderr.decode('utf-8', errors='backslashreplace') if audio_proc.stderr else ""
                if len(audio_raw) > 0:
                    audio_tensor = torch.frombuffer(bytearray(audio_raw), dtype=torch.float32)
                    match = re.search(r', (\d+) Hz, (\w+), ', audio_stderr)
                    if match:
                        ar = int(match.group(1))
                        ac = {"mono": 1, "stereo": 2}.get(match.group(2), 2)
                    else:
                        ar = 44100
                        ac = 2
                    audio_tensor = audio_tensor.reshape((-1, ac)).transpose(0, 1).unsqueeze(0)
                    audio_output = {"waveform": audio_tensor, "sample_rate": ar}
                    print(f"[Video Loader Simple] 오디오 로드 완료: {ar}Hz, {ac}ch")
        except Exception as e:
            print(f"[Video Loader Simple] 오디오 로드 실패: {e}")

        # 영상이 들어있는 폴더 이름 (전체 경로 아닌)
        parent_folder_name = os.path.basename(os.path.dirname(os.path.abspath(full_path)))

        first_frame = frames_tensor[0:1].clone()
        last_frame = frames_tensor[-1:].clone()

        return (frames_tensor, audio_output, filename_out, os.path.abspath(full_path), parent_folder_name, num_frames, target_fps, width, height, first_frame, last_frame)


class VideoFromFolderLoaderChunk:
    """
    영상 폴더에서 영상을 청크 단위로 자동 순환하며 로드.

    seed 하나만 increment하면 (영상 × 청크) 자동 순환:
      chunk_count=5, 영상 40개일 때 → seed 0~199 한 사이클
      seed 0: 영상[0] 청크[0]
      seed 1: 영상[0] 청크[1]
      ...
      seed 4: 영상[0] 청크[4]
      seed 5: 영상[1] 청크[0]

    ffmpeg -ss (input 앞, 정확 시크) + -frames:v로 해당 청크만 디코딩.
    → 메모리/디코딩 시간 약 1/chunk_count.
    """
    sort_methods = ["Numerical (ASC)", "Numerical (DESC)", "Alphabetical (ASC)", "Alphabetical (DESC)", "Datetime (ASC)", "Datetime (DESC)", "Random"]
    path_output_modes = ["filename_no_ext", "filename_with_ext", "full_path", "relative_path"]
    video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v']

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder_path": ("STRING", {"default": ""}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "chunk_count": ("INT", {"default": 1, "min": 1, "max": 32, "step": 1}),
                "overlap_frames": ("INT", {"default": 0, "min": 0, "max": 8, "step": 1, "tooltip": "다음 청크와 겹칠 프레임 수. 보간/SR 후 접합부 튐 방지용. 보간만 쓰면 1, 비디오 SR이면 2~3 권장. 마지막 청크는 항상 0."}),
                "stop_after_one_cycle": ("BOOLEAN", {"default": True, "label_on": "stop after cycle", "label_off": "infinite loop"}),
                "include_subfolders": ("BOOLEAN", {"default": False}),
                "sort_method": (cls.sort_methods, {"default": "Numerical (ASC)"}),
                "path_output_mode": (cls.path_output_modes, {"default": "filename_no_ext"}),
                "force_fps": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 240.0, "step": 0.01}),
                "frame_load_cap": ("INT", {"default": 0, "min": 0, "max": 100000, "step": 1}),
                "skip_first_frames": ("INT", {"default": 0, "min": 0, "max": 100000, "step": 1}),
                "hw_decode": (["auto", "cpu", "cuda", "qsv", "d3d11va"], {"default": "auto"}),
                "output_dtype": (["float32", "float16", "uint8"], {"default": "float32"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "AUDIO", "STRING", "STRING", "STRING", "INT", "FLOAT", "INT", "INT", "INT", "INT", "INT", "INT")
    RETURN_NAMES = ("frames", "audio", "filename", "full_path", "parent_folder", "frame_count", "fps", "width", "height", "current_chunk_index", "current_video_index", "total_iterations", "overlap_count")
    FUNCTION = "load_video"
    CATEGORY = "video"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")  # 항상 실행

    def _get_ffmpeg_paths(self):
        return VideoFromFolderLoader._get_ffmpeg_paths(self)

    def _run_subprocess(self, cmd, capture=True):
        return VideoFromFolderLoader._run_subprocess(self, cmd, capture)

    def natural_key(self, s):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]

    def sort_files(self, items, base_path, method, seed=0):
        def get_ts(name):
            try:
                return os.path.getmtime(os.path.join(base_path, name))
            except:
                return float('-inf')
        if method == "Alphabetical (ASC)": return sorted(items)
        elif method == "Alphabetical (DESC)": return sorted(items, reverse=True)
        elif method == "Numerical (ASC)": return sorted(items, key=self.natural_key)
        elif method == "Numerical (DESC)": return sorted(items, key=self.natural_key, reverse=True)
        elif method == "Datetime (ASC)": return sorted(items, key=get_ts)
        elif method == "Datetime (DESC)": return sorted(items, key=get_ts, reverse=True)
        elif method == "Random":
            r = random.Random(seed)
            items_copy = list(items)
            r.shuffle(items_copy)
            return items_copy
        else: return items

    def load_video(self, folder_path, seed=0, chunk_count=1, overlap_frames=0, stop_after_one_cycle=True,
                   include_subfolders=False, sort_method="Numerical (ASC)",
                   path_output_mode="filename_no_ext", force_fps=0.0, frame_load_cap=0,
                   skip_first_frames=0, hw_decode="auto", output_dtype="float32"):
        import json as _json

        ffmpeg_exe, ffprobe_exe = self._get_ffmpeg_paths()

        if not os.path.isdir(folder_path):
            raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {folder_path}")

        # 영상 파일 수집
        video_files = []
        if include_subfolders:
            for root, dirs, files in os.walk(folder_path):
                for f in files:
                    if any(f.lower().endswith(ext) for ext in self.video_extensions):
                        rel = os.path.relpath(os.path.join(root, f), folder_path)
                        video_files.append(rel)
        else:
            for f in os.listdir(folder_path):
                if any(f.lower().endswith(ext) for ext in self.video_extensions):
                    video_files.append(f)

        if not video_files:
            raise RuntimeError(f"영상 파일이 없습니다: {folder_path}")

        video_files = self.sort_files(video_files, folder_path, sort_method, seed)

        # 청크 순환 로직: seed 하나로 (영상, 청크) 자동 순환
        num_videos = len(video_files)
        chunk_count = max(1, int(chunk_count))
        total_iterations = num_videos * chunk_count

        # stop_after_one_cycle: seed가 한 사이클 넘어가면 정지
        if stop_after_one_cycle and seed >= total_iterations:
            raise RuntimeError(
                f"\n"
                f"{'='*60}\n"
                f"🛑 한 사이클 완료 - 작업 정지\n"
                f"{'='*60}\n"
                f"   현재 seed: {seed}\n"
                f"   총 iteration: {total_iterations} (영상 {num_videos}개 × 청크 {chunk_count})\n"
                f"   seed {seed} >= {total_iterations} 이므로 모든 영상×청크 처리 완료.\n"
                f"\n"
                f"   ▶ 다시 돌리려면:\n"
                f"     - seed를 0으로 리셋 후 큐 재시작\n"
                f"     - 또는 stop_after_one_cycle 토글을 끄면 무한 순환\n"
                f"{'='*60}"
            )

        cycle_pos = seed % total_iterations
        video_idx = cycle_pos // chunk_count
        chunk_idx = cycle_pos % chunk_count

        chosen = video_files[video_idx]
        full_path = os.path.join(folder_path, chosen)

        print(f"[Video Loader Chunk] seed={seed} → 영상 [{video_idx+1}/{num_videos}] 청크 [{chunk_idx+1}/{chunk_count}] (total_iter={total_iterations}): {chosen}")

        # filename 출력
        if path_output_mode == "filename_no_ext":
            filename_out = os.path.splitext(os.path.basename(chosen))[0]
        elif path_output_mode == "filename_with_ext":
            filename_out = os.path.basename(chosen)
        elif path_output_mode == "full_path":
            filename_out = os.path.abspath(full_path)
        else:  # relative_path
            filename_out = chosen

        # ffprobe
        probe_cmd = [ffprobe_exe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", full_path]
        try:
            result = self._run_subprocess(probe_cmd)
            stdout = result.stdout.decode('utf-8', errors='ignore') if result.stdout else ""
            stderr = result.stderr.decode('utf-8', errors='ignore') if result.stderr else ""
            if result.returncode != 0:
                raise RuntimeError(f"ffprobe 실패 (returncode={result.returncode}): {stderr}")
            if not stdout.strip():
                raise RuntimeError(f"ffprobe가 빈 출력 반환. stderr: {stderr}")
            probe_data = _json.loads(stdout)
        except FileNotFoundError as e:
            raise RuntimeError(f"ffprobe 실행파일을 찾을 수 없음: {e}")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"ffprobe 실행 실패: {type(e).__name__}: {e}")

        video_stream = None
        audio_stream = None
        for s in probe_data.get("streams", []):
            if s.get("codec_type") == "video" and video_stream is None:
                video_stream = s
            elif s.get("codec_type") == "audio" and audio_stream is None:
                audio_stream = s

        if video_stream is None:
            raise RuntimeError(f"영상 스트림을 찾을 수 없습니다: {full_path}")

        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))

        fps_str = video_stream.get("r_frame_rate", "0/1")
        try:
            num, den = fps_str.split("/")
            orig_fps = float(num) / float(den) if float(den) > 0 else 0.0
        except:
            orig_fps = 0.0
        target_fps = force_fps if force_fps > 0 else orig_fps

        # 영상 전체 프레임/길이 추정
        nb_frames_str = video_stream.get("nb_frames", "0")
        try:
            total_video_frames = int(nb_frames_str) if nb_frames_str.isdigit() else 0
        except:
            total_video_frames = 0
        try:
            duration_total = float(probe_data.get("format", {}).get("duration", 0))
        except:
            duration_total = 0.0
        if total_video_frames == 0 and orig_fps > 0 and duration_total > 0:
            total_video_frames = int(duration_total * orig_fps)

        # 청크의 프레임 범위 (정수 계산으로 정확하게)
        # overlap_frames: 다음 청크와 겹칠 프레임 수 (마지막 청크는 0)
        if total_video_frames > 0:
            chunk_start_frame = (total_video_frames * chunk_idx) // chunk_count
            if chunk_idx == chunk_count - 1:
                chunk_end_frame = total_video_frames  # 마지막 청크는 끝까지, overlap 없음
                overlap_count_out = 0
            else:
                base_end = (total_video_frames * (chunk_idx + 1)) // chunk_count
                # 다음 청크 시작 = base_end. overlap_frames만큼 더 디코딩
                chunk_end_frame = min(base_end + overlap_frames, total_video_frames)
                overlap_count_out = chunk_end_frame - base_end  # 영상 끝 한계로 줄어들 수 있음
            chunk_frame_count = chunk_end_frame - chunk_start_frame
        else:
            chunk_start_frame = 0
            chunk_end_frame = 0
            chunk_frame_count = 0
            overlap_count_out = 0

        # 시크 시간 / 청크 길이
        if orig_fps > 0:
            chunk_start_time = chunk_start_frame / orig_fps
            chunk_duration = chunk_frame_count / orig_fps if chunk_frame_count > 0 else 0.0
        elif duration_total > 0:
            chunk_start_time = (duration_total * chunk_idx) / chunk_count
            chunk_duration = duration_total / chunk_count
        else:
            chunk_start_time = 0.0
            chunk_duration = 0.0

        # skip_first_frames는 청크 내부에서 적용 (청크 시작 이후 N프레임 스킵)
        effective_frame_count = max(0, chunk_frame_count - skip_first_frames)
        expected_frames = effective_frame_count
        if force_fps > 0 and orig_fps > 0:
            expected_frames = int(expected_frames * (force_fps / orig_fps))
        if frame_load_cap > 0:
            expected_frames = min(expected_frames, frame_load_cap) if expected_frames > 0 else frame_load_cap

        if overlap_count_out > 0:
            print(f"[Video Loader Chunk] 청크 범위: 프레임 [{chunk_start_frame}~{chunk_end_frame}] ({chunk_frame_count}프레임, 끝 {overlap_count_out}프레임 오버랩) / "
                  f"시간 [{chunk_start_time:.3f}s + {chunk_duration:.3f}s] / 예상 출력: {expected_frames}프레임")
        else:
            print(f"[Video Loader Chunk] 청크 범위: 프레임 [{chunk_start_frame}~{chunk_end_frame}] ({chunk_frame_count}프레임) / "
                  f"시간 [{chunk_start_time:.3f}s + {chunk_duration:.3f}s] / 예상 출력: {expected_frames}프레임")

        # ffmpeg 명령 (GPU 디코딩 + 청크 시크)
        def _build_ffmpeg_cmd(hwaccel_mode):
            cmd = [ffmpeg_exe, "-v", "error"]
            # -ss를 -i 앞에 두면: 모던 ffmpeg에서 정확 시크 (키프레임 기반 빠른 시크 + 프레임 정확 보정)
            if chunk_start_time > 0.001:
                cmd += ["-ss", f"{chunk_start_time:.6f}"]
            if hwaccel_mode == "cuda":
                cmd += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
            elif hwaccel_mode == "qsv":
                cmd += ["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"]
            elif hwaccel_mode == "d3d11va":
                cmd += ["-hwaccel", "d3d11va"]
            cmd += ["-i", full_path]
            # 마지막 청크 아니면 -t로 디코딩 길이 제한 (작은 버퍼 추가)
            if chunk_idx < chunk_count - 1 and chunk_duration > 0:
                cmd += ["-t", f"{chunk_duration + 0.5:.6f}"]
            local_vf = []
            if hwaccel_mode in ("cuda", "qsv"):
                local_vf.append("hwdownload")
                local_vf.append("format=nv12")
            if skip_first_frames > 0:
                local_vf.append(f"select='gte(n,{skip_first_frames})'")
                local_vf.append("setpts=PTS-STARTPTS")
            if force_fps > 0:
                local_vf.append(f"fps={force_fps}")
            if local_vf:
                cmd += ["-vf", ",".join(local_vf)]
            # 프레임 수 제한: -frames:v를 모든 청크에 적용 (마지막 청크 포함)
            # 마지막 청크에도 -frames:v를 박아야 ffmpeg가 정확히 그만큼만 출력하고
            # 정상 종료함. 안 박으면 Windows에서 broken pipe로 returncode=1 발생.
            limit = 0
            if effective_frame_count > 0:
                limit = effective_frame_count
                if force_fps > 0 and orig_fps > 0:
                    limit = int(limit * (force_fps / orig_fps))
            if frame_load_cap > 0:
                limit = frame_load_cap if limit == 0 else min(limit, frame_load_cap)
            if limit > 0:
                cmd += ["-frames:v", str(limit)]
            cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
            return cmd

        if hw_decode == "auto":
            tried_modes = ["cuda", "cpu"]
        else:
            tried_modes = [hw_decode]

        # ProgressBar
        try:
            from comfy.utils import ProgressBar
            pbar = ProgressBar(expected_frames) if expected_frames > 0 else None
        except Exception:
            pbar = None

        # ffmpeg 추출 (Simple과 동일 로직)
        frame_size = width * height * 3
        import threading
        from collections import deque
        import subprocess as _sp
        import platform as _pf

        # hang 감지용 타임아웃 (초)
        INIT_TIMEOUT = 30.0   # ffmpeg 첫 프레임 출력까지 (시크/초기화)
        STALL_TIMEOUT = 60.0  # 첫 프레임 이후 새 데이터 없을 때

        def _do_extract(cmd):
            import time as _t
            popen_kw = {"stdout": _sp.PIPE, "stderr": _sp.PIPE, "bufsize": 1024 * 1024 * 8}
            if _pf.system() == "Windows":
                si = _sp.STARTUPINFO()
                si.dwFlags |= _sp.STARTF_USESHOWWINDOW
                popen_kw["startupinfo"] = si
            proc = _sp.Popen(cmd, **popen_kw)
            stderr_buf = deque(maxlen=200)

            # watchdog 상태 (mutable container for thread sharing)
            last_data_time = [_t.time()]
            first_data_received = [False]
            aborted = [False]
            abort_reason = [""]

            def _watchdog():
                while proc.poll() is None and not aborted[0]:
                    now = _t.time()
                    since_last = now - last_data_time[0]
                    timeout_to_use = INIT_TIMEOUT if not first_data_received[0] else STALL_TIMEOUT
                    if since_last > timeout_to_use:
                        phase = "초기화/시크" if not first_data_received[0] else "스트리밍"
                        abort_reason[0] = f"ffmpeg {phase} 단계에서 {timeout_to_use:.0f}초 응답 없음 (hang으로 판단)"
                        print(f"[Video Loader Chunk] ⏰ {abort_reason[0]} → 강제 종료")
                        stderr_snapshot = "\n".join(list(stderr_buf)[-20:])
                        if stderr_snapshot.strip():
                            print(f"[Video Loader Chunk] 강제 종료 시점 stderr:\n{stderr_snapshot}")
                        else:
                            print(f"[Video Loader Chunk] stderr 출력 없음 (ffmpeg가 아무것도 안 찍는 상태)")
                        aborted[0] = True
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        break
                    _t.sleep(2.0)

            watchdog_thread = threading.Thread(target=_watchdog, daemon=True)
            watchdog_thread.start()

            def _drain(pipe, buf):
                try:
                    for line in iter(pipe.readline, b''):
                        if not line:
                            break
                        buf.append(line.decode('utf-8', errors='ignore').rstrip())
                except Exception:
                    pass
            stderr_thread = threading.Thread(target=_drain, args=(proc.stderr, stderr_buf), daemon=True)
            stderr_thread.start()

            def _mark_data():
                if not first_data_received[0]:
                    first_data_received[0] = True
                    print(f"[Video Loader Chunk] ▶ 첫 프레임 수신 (시크 통과)")
                last_data_time[0] = _t.time()

            if expected_frames > 0:
                _frames_np = np.empty((expected_frames, height, width, 3), dtype=np.uint8)
                idx = 0
                READ_BATCH = max(1, min(16, expected_frames, max(1, (4 * 1024 * 1024) // frame_size)))
                read_size = frame_size * READ_BATCH
                while idx < expected_frames:
                    data = proc.stdout.read(read_size)
                    if not data:
                        break
                    _mark_data()
                    n_recv = len(data) // frame_size
                    if n_recv == 0:
                        break
                    arr = np.frombuffer(data, dtype=np.uint8, count=n_recv * frame_size).reshape((n_recv, height, width, 3))
                    end = min(idx + n_recv, expected_frames)
                    _frames_np[idx:end] = arr[:end - idx]
                    if pbar is not None:
                        pbar.update(end - idx)
                    idx = end
                _num = idx
                if _num < expected_frames:
                    _frames_np = _frames_np[:_num]
            else:
                chunks = []
                READ_BATCH = max(1, (4 * 1024 * 1024) // frame_size)
                read_size = frame_size * READ_BATCH
                while True:
                    data = proc.stdout.read(read_size)
                    if not data:
                        break
                    _mark_data()
                    n_recv = len(data) // frame_size
                    if n_recv == 0:
                        break
                    arr = np.frombuffer(data, dtype=np.uint8, count=n_recv * frame_size).reshape((n_recv, height, width, 3)).copy()
                    chunks.append(arr)
                    if pbar is not None:
                        pbar.update(n_recv)
                if chunks:
                    _frames_np = np.concatenate(chunks, axis=0)
                else:
                    _frames_np = np.empty((0, height, width, 3), dtype=np.uint8)
                _num = _frames_np.shape[0]
            try:
                proc.wait(timeout=10.0)
            except _sp.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                proc.wait()
            stderr_thread.join(timeout=2.0)
            stderr_text = "\n".join(list(stderr_buf)[-30:])
            if aborted[0]:
                raise RuntimeError(
                    f"{abort_reason[0]}\n"
                    f"--- 실행 명령 ---\n{' '.join(cmd)}\n"
                    f"--- 최근 stderr ---\n{stderr_text if stderr_text.strip() else '(없음)'}"
                )
            if proc.returncode != 0:
                # broken pipe 케이스 관용: 데이터를 정상 수신했고 stderr가 비어있으면
                # ffmpeg가 stdout write 실패로 종료한 것으로 추정, 성공 처리
                # (expected_frames 다 받았으면 그 뒤 데이터는 어차피 버릴 거였음)
                if _num > 0 and not stderr_text.strip():
                    print(f"[Video Loader Chunk] ⚠️ ffmpeg returncode={proc.returncode} + stderr 비어있음 + {_num}프레임 수신 → broken pipe 추정, 성공 처리")
                else:
                    raise RuntimeError(f"ffmpeg 실행 실패 (returncode={proc.returncode}):\n{stderr_text}")
            return _frames_np, _num

        frames_np = None
        num_frames = 0
        last_err = None
        import time as _time
        for try_idx, mode in enumerate(tried_modes):
            try:
                cmd_try = _build_ffmpeg_cmd(mode)
                _t_decode_start = _time.time()
                print(f"[Video Loader Chunk] ffmpeg 디코딩 시도: {mode}")
                print(f"[Video Loader Chunk] 명령: {' '.join(cmd_try)}")
                try:
                    from comfy.utils import ProgressBar
                    if expected_frames > 0:
                        pbar = ProgressBar(expected_frames)
                except Exception:
                    pass
                frames_np, num_frames = _do_extract(cmd_try)
                if num_frames > 0:
                    print(f"[Video Loader Chunk] ✅ {mode} 성공: {num_frames}프레임 ({_time.time()-_t_decode_start:.1f}초)")
                    break
                last_err = f"{mode}: 프레임 0개"
            except FileNotFoundError as e:
                raise RuntimeError(f"ffmpeg 실행파일을 찾을 수 없음: {e}")
            except Exception as e:
                last_err = str(e)
                print(f"[Video Loader Chunk] ⚠️ {mode} 실패: {str(e)[:300]}")
                if try_idx < len(tried_modes) - 1:
                    print(f"[Video Loader Chunk] → {tried_modes[try_idx+1]}로 fallback")
                continue

        if not num_frames or frames_np is None:
            raise RuntimeError(f"모든 디코딩 모드 실패. 마지막 에러:\n{last_err}")

        _t_conv_start = _time.time()
        # dtype 변환 (Simple과 동일 로직)
        try:
            from comfy.utils import ProgressBar as _PB
            _conv_pbar = _PB(num_frames)
        except Exception:
            _conv_pbar = None

        _gpu_available = False
        try:
            _gpu_available = torch.cuda.is_available()
        except Exception:
            pass

        if output_dtype == "uint8":
            frames_tensor = torch.from_numpy(frames_np)
            if _conv_pbar is not None:
                _conv_pbar.update(num_frames)
        elif output_dtype == "float16":
            target_dtype = torch.float16
            if num_frames > 50:
                frames_tensor = torch.empty((num_frames, height, width, 3), dtype=target_dtype)
                CHUNK = 64
                for i in range(0, num_frames, CHUNK):
                    end = min(i + CHUNK, num_frames)
                    if _gpu_available:
                        chunk_uint8 = torch.from_numpy(frames_np[i:end]).cuda(non_blocking=True)
                        frames_tensor[i:end] = (chunk_uint8.to(target_dtype) / 255.0).cpu()
                        del chunk_uint8
                    else:
                        frames_tensor[i:end] = torch.from_numpy(frames_np[i:end]).to(target_dtype).div_(255.0)
                    if _conv_pbar is not None:
                        _conv_pbar.update(end - i)
                del frames_np
                if _gpu_available:
                    torch.cuda.empty_cache()
            else:
                if _gpu_available:
                    frames_tensor = (torch.from_numpy(frames_np).cuda().to(target_dtype) / 255.0).cpu()
                else:
                    frames_tensor = torch.from_numpy(frames_np).to(target_dtype) / 255.0
        else:
            if num_frames > 50:
                frames_tensor = torch.empty((num_frames, height, width, 3), dtype=torch.float32)
                CHUNK = 32
                for i in range(0, num_frames, CHUNK):
                    end = min(i + CHUNK, num_frames)
                    if _gpu_available:
                        chunk_uint8 = torch.from_numpy(frames_np[i:end]).cuda(non_blocking=True)
                        frames_tensor[i:end] = (chunk_uint8.float() / 255.0).cpu()
                        del chunk_uint8
                    else:
                        frames_tensor[i:end] = torch.from_numpy(frames_np[i:end]).float().div_(255.0)
                    if _conv_pbar is not None:
                        _conv_pbar.update(end - i)
                del frames_np
                if _gpu_available:
                    torch.cuda.empty_cache()
            else:
                if _gpu_available:
                    frames_tensor = (torch.from_numpy(frames_np).cuda().float() / 255.0).cpu()
                else:
                    frames_tensor = torch.from_numpy(frames_np).float() / 255.0

        print(f"[Video Loader Chunk] dtype 변환 완료 ({_time.time()-_t_conv_start:.1f}초, {num_frames}프레임)")

        # 오디오 로드 (해당 청크 시간 범위만)
        audio_output = {"waveform": torch.zeros((1, 2, 1)), "sample_rate": 44100}
        try:
            audio_cmd = [ffmpeg_exe]
            if chunk_start_time > 0.001:
                audio_cmd += ["-ss", f"{chunk_start_time:.6f}"]
            audio_cmd += ["-i", full_path]
            if chunk_idx < chunk_count - 1 and chunk_duration > 0:
                audio_cmd += ["-t", f"{chunk_duration:.6f}"]
            audio_cmd += ["-vn", "-f", "f32le", "-"]
            kw = {"capture_output": True, "timeout": 60}  # 오디오 추출 60초 한도
            if _pf.system() == "Windows":
                si = _sp.STARTUPINFO()
                si.dwFlags |= _sp.STARTF_USESHOWWINDOW
                kw["startupinfo"] = si
            try:
                audio_proc = _sp.run(audio_cmd, **kw)
            except _sp.TimeoutExpired:
                print(f"[Video Loader Chunk] ⚠️ 오디오 추출 60초 timeout - 스킵")
                audio_proc = None
            if audio_proc is not None:
                audio_raw = audio_proc.stdout if audio_proc.stdout else b""
                audio_stderr = audio_proc.stderr.decode('utf-8', errors='backslashreplace') if audio_proc.stderr else ""
                if len(audio_raw) > 0:
                    audio_tensor = torch.frombuffer(bytearray(audio_raw), dtype=torch.float32)
                    match = re.search(r', (\d+) Hz, (\w+), ', audio_stderr)
                    if match:
                        ar = int(match.group(1))
                        ac = {"mono": 1, "stereo": 2}.get(match.group(2), 2)
                    else:
                        ar = 44100
                        ac = 2
                    audio_tensor = audio_tensor.reshape((-1, ac)).transpose(0, 1).unsqueeze(0)
                    audio_output = {"waveform": audio_tensor, "sample_rate": ar}
                    print(f"[Video Loader Chunk] 오디오 로드 완료: {ar}Hz, {ac}ch (청크 범위)")
        except Exception as e:
            print(f"[Video Loader Chunk] 오디오 로드 실패: {e}")

        parent_folder_name = os.path.basename(os.path.dirname(os.path.abspath(full_path)))

        return (frames_tensor, audio_output, filename_out, os.path.abspath(full_path),
                parent_folder_name, num_frames, target_fps, width, height,
                int(chunk_idx), int(video_idx), int(total_iterations), int(overlap_count_out))


class WildcardCombiner:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "action": ("STRING", {"multiline": True, "default": "action1\naction2\naction3"}),
                "char_separator": ("STRING", {"default": ", "}),
                "action_separator": ("STRING", {"default": ", "}),
                "mode": (["multiply", "sync", "paired_chars", "grouped"], {"default": "multiply"}),
                "action_chunk_size": ("INT", {"default": 0, "min": 0, "max": 10000}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 999999}),
            },
            "optional": FlexibleOptionalInputType(type=any_type, data={}),
        }

    RETURN_TYPES = ByPassTypeTuple(("STRING", "STRING", "STRING"))
    RETURN_NAMES = CharNamesTypeTuple(("combined", "current_action", "help"))
    FUNCTION = "combine"
    CATEGORY = "image/animation"

    @staticmethod
    def _build_help(mode, num_chars, num_char_inputs, total_char_count, count_actions, count_pairs, action_chunk_size, seed):
        """현재 모드 + 상태에 맞는 도움말 텍스트 생성"""
        mode_explanations = {
            "multiply": (
                "[multiply] 캐 여러 명을 한 화면에 같이 그릴 때 사용.\n"
                "  char_1, char_2... 슬롯이 같은 인덱스로 짝지어져 동시 출력.\n"
                "  예) char_1=[A,B] char_2=[X,Y] action=[a1,a2]\n"
                "    seed 0: 'A, X, a1' / seed 1: 'A, X, a2'\n"
                "    seed 2: 'B, Y, a1' / seed 3: 'B, Y, a2'\n"
                f"  순환 주기 = char쌍 수({count_pairs}) × action({count_actions}) = {count_pairs * count_actions}\n"
                "  ✔ 캐 2명 동시 등장 / before-after 비교 / 동기화된 페어 출력"
            ),
            "sync": (
                "[sync] 캐 1명이 action 청크 N개 다 돌면 다음 캐로.\n"
                "  모든 char_N 슬롯의 줄을 합쳐서 평탄화 후 순회.\n"
                "  한 번에 한 명만 출력 (다른 슬롯은 빈값).\n"
                f"  현재 chunk_size={action_chunk_size if action_chunk_size > 0 else 1}, "
                f"평탄화된 캐 수={total_char_count}, action={count_actions}\n"
                "  예) chunk=3, char=[A,B], action=[a,b,c]\n"
                "    seed 0~2: A + a/b/c\n"
                "    seed 3~5: B + a/b/c\n"
                "  ✔ 캐별 시리즈 / 캐 1명에 액션 패턴 반복"
            ),
            "paired_chars": (
                "[paired_chars] 캐를 번갈아 출력 (인터리브).\n"
                "  char_1의 [0], char_2의 [0], char_1의 [1], char_2의 [1] ...\n"
                "  한 번에 한 명만 출력.\n"
                f"  현재 char 슬롯 수={num_char_inputs}, 쌍 수={count_pairs}, action={count_actions}\n"
                "  예) char_1=[A1,A2] char_2=[B1,B2]\n"
                "    seed 0: A1 / seed 1: B1 / seed 2: A2 / seed 3: B2\n"
                "  ✔ 캐별 영상 번갈아 / A,B,A,B 패턴"
            ),
            "grouped": (
                "[grouped] action을 캐 수로 균등 분할, 각 캐는 자기 구간만 사용.\n"
                "  한 번에 한 명만 출력.\n"
                f"  평탄화된 캐 수={total_char_count}, action={count_actions}, "
                f"캐당 그룹 크기={max(1, count_actions // max(1, total_char_count))}\n"
                "  예) action 30줄 + 캐 3명\n"
                "    캐1 = action[0~9] / 캐2 = action[10~19] / 캐3 = action[20~29]\n"
                "  ✔ 캐별로 전용 action 시리즈 적용"
            ),
        }
        header = f"=== Wildcard Combiner 모드: {mode} | seed={seed} ===\n"
        explanation = mode_explanations.get(mode, f"알 수 없는 모드: {mode}")
        return header + explanation

    def combine(self, action, char_separator=", ", action_separator=", ", mode="multiply", action_chunk_size=0, seed=0, **kwargs):
        # char_ 로 시작하는 키만 수집 (순서 보장)
        char_lists = []
        char_keys = sorted([k for k in kwargs.keys() if re.match(r"^char_\d+$", k)],
                          key=lambda k: int(k.split("_")[1]) if k.split("_")[1].isdigit() else 999)
        for key in char_keys:
            val = kwargs[key]
            if isinstance(val, str):
                parsed = [w.strip() for w in val.split('\n') if w.strip()]
                if parsed:
                    char_lists.append((key, parsed))

        actions = [w.strip() for w in action.split('\n') if w.strip()]
        num_char_inputs = len(char_keys)

        # help 텍스트 미리 만들 정보
        count_actions_pre = len(actions)
        count_pairs_pre = min((len(c) for _, c in char_lists), default=0)
        total_char_count_pre = sum(len(c) for _, c in char_lists)

        empty_help = self._build_help(mode, len(char_lists), num_char_inputs,
                                       total_char_count_pre, count_actions_pre,
                                       count_pairs_pre, action_chunk_size, seed)
        empty_result = ("", "", empty_help) + ("",) * num_char_inputs
        if not char_lists or not actions:
            return empty_result

        count_actions = len(actions)
        count_pairs = min(len(c) for _, c in char_lists)
        num_chars = len(char_lists)
        current_chars_out = [""] * num_char_inputs

        if mode == "sync":
            # action_chunk_size 만큼 action 줄이 다 돌면 char가 다음으로 넘어감
            # 예: chunk_size=13, action 52줄, char 100명
            # seed 0~12: char1 + action[0~12] (와카1의 13줄)
            # seed 13~25: char2 + action[13~25] (와카2의 13줄)
            # seed 26~38: char3 + action[26~38]
            # ...
            # seed 52~64: char5 + action[0~12] (action wrap, char는 계속 진행)

            flat_chars = []
            for slot_idx, (key, cl) in enumerate(char_lists):
                for line in cl:
                    flat_chars.append((char_keys.index(key), line))

            total_char_count = len(flat_chars)
            if total_char_count == 0 or count_actions == 0:
                return empty_result

            # chunk_size가 0이면 단순 modulo sync
            chunk = action_chunk_size if action_chunk_size > 0 else 1

            char_idx = (seed // chunk) % total_char_count
            action_idx = seed % count_actions

            current_slot, current_char = flat_chars[char_idx]
            current_chars_out[current_slot] = current_char
            current_action = actions[action_idx]
            combined = current_char + action_separator + current_action
            print(f"[Wildcard Combiner] sync seed={seed} chunk={chunk} → char[{char_idx+1}/{total_char_count}] action[{action_idx+1}/{count_actions}]")

        elif mode == "paired_chars":
            # A1, B1, C1, A2, B2, C2... 순서
            total_per_cycle = count_pairs * num_chars
            idx = seed % total_per_cycle
            pair_idx = idx // num_chars
            char_idx = idx % num_chars
            action_index = seed % count_actions

            current_char = char_lists[char_idx][1][pair_idx]
            actual_key = char_lists[char_idx][0]
            actual_idx = char_keys.index(actual_key)
            current_chars_out[actual_idx] = current_char
            current_action = actions[action_index]
            combined = current_char + action_separator + current_action
            print(f"[Wildcard Combiner] paired_chars seed={seed} → char[{char_idx+1}] pair[{pair_idx+1}] action[{action_index+1}]")

        elif mode == "grouped":
            # action을 캐릭터 수로 균등 분할, 각 캐릭은 자기 그룹의 action만 사용
            # 캐릭터는 char_1, char_2... 여러 입력에 한 명씩 들어가거나
            # char_1에 여러 줄로 한꺼번에 들어갈 수 있음
            
            # 전체 캐릭터 리스트 (모든 char_N의 줄을 평탄화)
            flat_chars = []  # [(slot_idx, char_string), ...]
            for slot_idx, (key, cl) in enumerate(char_lists):
                for line in cl:
                    flat_chars.append((char_keys.index(key), line))
            
            total_char_count = len(flat_chars)
            if total_char_count == 0 or count_actions == 0:
                return empty_result
            
            # action을 캐릭터 수로 균등 분할
            group_size = count_actions // total_char_count
            if group_size < 1:
                group_size = 1
            
            total_iterations = total_char_count * group_size
            idx = seed % total_iterations if total_iterations > 0 else 0
            
            char_group_idx = idx // group_size       # 어느 캐릭터
            action_in_group = idx % group_size       # 그룹 내 몇 번째 action
            action_index = char_group_idx * group_size + action_in_group
            
            # 안전 체크
            if char_group_idx >= total_char_count:
                char_group_idx = total_char_count - 1
            if action_index >= count_actions:
                action_index = count_actions - 1
            
            current_slot, current_char = flat_chars[char_group_idx]
            current_chars_out[current_slot] = current_char
            current_action = actions[action_index]
            combined = current_char + action_separator + current_action
            print(f"[Wildcard Combiner] grouped seed={seed} → char[{char_group_idx+1}/{total_char_count}] action_in_group[{action_in_group+1}/{group_size}] (action_idx={action_index+1}/{count_actions})")

        else:  # multiply (기본)
            # 기존 동작: char × action 모든 조합
            pair_index = (seed // count_actions) % count_pairs
            action_index = seed % count_actions
            for _, (key, cl) in enumerate(char_lists):
                actual_idx = char_keys.index(key)
                current_chars_out[actual_idx] = cl[pair_index]
            current_action = actions[action_index]
            combined = char_separator.join([c for c in current_chars_out if c]) + action_separator + current_action
            print(f"[Wildcard Combiner] multiply seed={seed} → 쌍[{pair_index+1}/{count_pairs}] 행동[{action_index+1}/{count_actions}]")

        # 도움말 텍스트 생성 (현재 mode + 통계)
        total_char_count = sum(len(c) for _, c in char_lists)
        help_text = self._build_help(mode, num_chars, num_char_inputs,
                                     total_char_count, count_actions,
                                     count_pairs, action_chunk_size, seed)

        return (combined, current_action, help_text) + tuple(current_chars_out)


class StringToLatent:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt_string": ("STRING", {"multiline": True, "default": ""}),
                "default_width": ("INT", {"default": 512, "min": 64, "max": 8192, "step": 8}),
                "default_height": ("INT", {"default": 512, "min": 64, "max": 8192, "step": 8}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
            }
        }

    RETURN_TYPES = ("LATENT", "INT", "INT", "STRING")
    RETURN_NAMES = ("latent", "width", "height", "remaining_string")
    FUNCTION = "generate"
    CATEGORY = "latent"

    def generate(self, prompt_string, default_width=512, default_height=512, batch_size=1):
        width, height = default_width, default_height
        remaining_string = prompt_string
        for pattern in [r'resolution[:\s]*(\d+)\s*[x×]\s*(\d+)', r'res[:\s]*(\d+)\s*[x×]\s*(\d+)', r'(\d+)\s*[x×]\s*(\d+)']:
            match = re.search(pattern, prompt_string, re.IGNORECASE)
            if match:
                width, height = int(match.group(1)), int(match.group(2))
                remaining_string = prompt_string[:match.start()] + prompt_string[match.end():]
                break
        remaining_string = re.sub(r'\s*,\s*,+', ', ', remaining_string)
        remaining_string = re.sub(r'^[\s,]+|[\s,]+$', '', remaining_string)
        width = (width // 8) * 8
        height = (height // 8) * 8
        return ({"samples": torch.zeros([batch_size, 4, height // 8, width // 8])}, width, height, remaining_string)


class ImageSaver:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "filename_prefix": ("STRING", {"default": "image"}),
                "folder_path": ("STRING", {"default": "output/%time"}),
                "extension": (["webp", "png", "jpg", "jpeg"],),
                "quality_jpeg_or_webp": ("INT", {"default": 90, "min": 1, "max": 100, "step": 1}),
                "lossless_webp": ("BOOLEAN", {"default": False}),
                "optimize_png": ("BOOLEAN", {"default": False}),
                "embed_workflow": ("BOOLEAN", {"default": True}),
                "counter_digits": ("INT", {"default": 5, "min": 0, "max": 10}),
                "time_format": ("STRING", {"default": "%Y%m%d"}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"}
        }

    RETURN_TYPES = ()
    FUNCTION = "save_images"
    OUTPUT_NODE = True
    CATEGORY = "image"

    def save_images(self, images, filename_prefix="image", folder_path="output/%time", extension="webp",
                   quality_jpeg_or_webp=90, lossless_webp=False, optimize_png=False, embed_workflow=True,
                   counter_digits=5, time_format="%Y%m%d", prompt=None, extra_pnginfo=None):
        import json
        from datetime import datetime
        from PIL import Image as PILImage
        from PIL.PngImagePlugin import PngInfo
        from comfy.cli_args import args
        time_str = datetime.now().strftime(time_format)
        folder_path = folder_path.replace("%time", time_str)
        if not os.path.isabs(folder_path):
            import folder_paths
            full_path = os.path.join(folder_paths.get_output_directory(), folder_path)
        else:
            full_path = folder_path
        os.makedirs(full_path, exist_ok=True)
        existing_files = [f for f in os.listdir(full_path) if f.startswith(filename_prefix) and f.endswith(f".{extension}")]
        max_number = -1
        for f in existing_files:
            name_without_ext = os.path.splitext(f)[0]
            if name_without_ext.startswith(filename_prefix + "_"):
                try:
                    max_number = max(max_number, int(name_without_ext[len(filename_prefix)+1:]))
                except ValueError:
                    pass
        start_number = max_number + 1
        results = []
        for i in range(images.shape[0]):
            current_number = start_number + i
            full_filename = f"{filename_prefix}_{current_number:0{counter_digits}d}.{extension}" if counter_digits > 0 else f"{filename_prefix}_{current_number}.{extension}"
            file_path = os.path.join(full_path, full_filename)
            img_np = np.clip(255.0 * images[i].cpu().numpy(), 0, 255).astype(np.uint8)
            img_pil = PILImage.fromarray(img_np)
            save_kwargs = {}
            if extension == "png":
                save_kwargs["compress_level"] = 4
                if optimize_png: save_kwargs["optimize"] = True
                if embed_workflow and not args.disable_metadata:
                    metadata = PngInfo()
                    if prompt is not None: metadata.add_text("prompt", json.dumps(prompt))
                    if extra_pnginfo is not None:
                        for x in extra_pnginfo: metadata.add_text(x, json.dumps(extra_pnginfo[x]))
                    save_kwargs["pnginfo"] = metadata
            elif extension == "webp":
                save_kwargs["quality"] = quality_jpeg_or_webp
                if lossless_webp: save_kwargs["lossless"] = True
                save_kwargs["method"] = 6
            elif extension in ["jpg", "jpeg"]:
                save_kwargs["quality"] = quality_jpeg_or_webp
                save_kwargs["optimize"] = True
            img_pil.save(file_path, **save_kwargs)
            if extension in ["webp", "jpg", "jpeg"] and embed_workflow and not args.disable_metadata:
                try:
                    import piexif, piexif.helper
                    workflow_data = {}
                    if prompt is not None: workflow_data["prompt"] = prompt
                    if extra_pnginfo is not None: workflow_data.update(extra_pnginfo)
                    exif_bytes = piexif.dump({"Exif": {piexif.ExifIFD.UserComment: piexif.helper.UserComment.dump(json.dumps(workflow_data), encoding="unicode")}})
                    piexif.insert(exif_bytes, file_path)
                except ImportError:
                    print("[Image Saver] piexif 미설치")
            results.append({"filename": full_filename, "subfolder": folder_path, "type": "output"})
            print(f"[Image Saver] 저장: {full_filename}")
        return {"ui": {"images": results}}


class ImageSaverSeedCounter(ImageSaver):
    @classmethod
    def INPUT_TYPES(cls):
        inputs = super().INPUT_TYPES()
        required = dict(inputs["required"])
        new_required = {}
        for key, value in required.items():
            new_required[key] = value
            if key == "counter_digits":
                new_required["counter_source"] = (["seed", "auto"], {"default": "seed"})
                new_required["seed_counter"] = ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 0xffffffffffffffff,
                    "step": 1,
                    "forceInput": True,
                })
        inputs["required"] = new_required
        return inputs

    FUNCTION = "save_images"
    OUTPUT_NODE = True
    CATEGORY = "image"

    def save_images(self, images, filename_prefix="image", folder_path="output/%time", extension="webp",
                   quality_jpeg_or_webp=90, lossless_webp=False, optimize_png=False, embed_workflow=True,
                   counter_digits=5, counter_source="seed", seed_counter=0, time_format="%Y%m%d",
                   prompt=None, extra_pnginfo=None):
        import json
        from datetime import datetime
        from PIL import Image as PILImage
        from PIL.PngImagePlugin import PngInfo
        from comfy.cli_args import args

        time_str = datetime.now().strftime(time_format)
        folder_path = folder_path.replace("%time", time_str)
        if not os.path.isabs(folder_path):
            import folder_paths
            full_path = os.path.join(folder_paths.get_output_directory(), folder_path)
        else:
            full_path = folder_path
        os.makedirs(full_path, exist_ok=True)

        if counter_source == "seed":
            start_number = int(seed_counter)
        else:
            existing_files = [f for f in os.listdir(full_path) if f.startswith(filename_prefix) and f.endswith(f".{extension}")]
            max_number = -1
            for f in existing_files:
                name_without_ext = os.path.splitext(f)[0]
                if name_without_ext.startswith(filename_prefix + "_"):
                    try:
                        max_number = max(max_number, int(name_without_ext[len(filename_prefix)+1:]))
                    except ValueError:
                        pass
            start_number = max_number + 1

        results = []
        for i in range(images.shape[0]):
            current_number = start_number + i
            if counter_digits > 0:
                full_filename = f"{filename_prefix}_{current_number:0{counter_digits}d}.{extension}"
            else:
                full_filename = f"{filename_prefix}_{current_number}.{extension}"
            file_path = os.path.join(full_path, full_filename)
            img_np = np.clip(255.0 * images[i].cpu().numpy(), 0, 255).astype(np.uint8)
            img_pil = PILImage.fromarray(img_np)
            save_kwargs = {}
            if extension == "png":
                save_kwargs["compress_level"] = 4
                if optimize_png:
                    save_kwargs["optimize"] = True
                if embed_workflow and not args.disable_metadata:
                    metadata = PngInfo()
                    if prompt is not None:
                        metadata.add_text("prompt", json.dumps(prompt))
                    if extra_pnginfo is not None:
                        for x in extra_pnginfo:
                            metadata.add_text(x, json.dumps(extra_pnginfo[x]))
                    save_kwargs["pnginfo"] = metadata
            elif extension == "webp":
                save_kwargs["quality"] = quality_jpeg_or_webp
                if lossless_webp:
                    save_kwargs["lossless"] = True
                save_kwargs["method"] = 6
            elif extension in ["jpg", "jpeg"]:
                save_kwargs["quality"] = quality_jpeg_or_webp
                save_kwargs["optimize"] = True
            img_pil.save(file_path, **save_kwargs)
            if extension in ["webp", "jpg", "jpeg"] and embed_workflow and not args.disable_metadata:
                try:
                    import piexif, piexif.helper
                    workflow_data = {}
                    if prompt is not None:
                        workflow_data["prompt"] = prompt
                    if extra_pnginfo is not None:
                        workflow_data.update(extra_pnginfo)
                    exif_bytes = piexif.dump({"Exif": {piexif.ExifIFD.UserComment: piexif.helper.UserComment.dump(json.dumps(workflow_data), encoding="unicode")}})
                    piexif.insert(exif_bytes, file_path)
                except ImportError:
                    print("[Image Saver Seed Counter] piexif is not installed; metadata was skipped.")
            results.append({"filename": full_filename, "subfolder": folder_path, "type": "output"})
            print(f"[Image Saver Seed Counter] saved {full_filename}")
        return {"ui": {"images": results}}


def _load_save_image_extended_base():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    custom_nodes_dir = os.path.dirname(current_dir)
    local_module_path = os.path.join(current_dir, "save_image_extended_base.py")
    module_path = local_module_path
    if not os.path.isfile(module_path):
        module_path = os.path.join(custom_nodes_dir, "save-image-extended-comfyui", "save_image_extended.py")
    if not os.path.isfile(module_path):
        raise ImportError(f"save-image-extended-comfyui를 찾을 수 없습니다: {module_path}")
    spec = importlib.util.spec_from_file_location("_wildcard_save_image_extended", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SaveImageExtended


_SaveImageExtendedBase = _load_save_image_extended_base()


class SaveImageExtendedSeedCounterWildcard(_SaveImageExtendedBase):
    @classmethod
    def INPUT_TYPES(cls):
        inputs = super().INPUT_TYPES()
        required = dict(inputs.get("required", {}))
        new_required = {}
        inserted = False

        for key, value in required.items():
            if key == "counter_digits" and isinstance(value, tuple) and len(value) > 1 and isinstance(value[1], dict):
                config = dict(value[1])
                config["min"] = 0
                value = (value[0], config)

            new_required[key] = value
            if key == "counter_digits":
                new_required["counter_source"] = (["seed", "auto"], {"default": "seed"})
                new_required["seed_counter"] = ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 0xffffffffffffffff,
                    "step": 1,
                    "forceInput": True,
                    "tooltip": "counter_source가 seed면 이 값이 파일명 카운터로 들어갑니다.",
                })
                new_required["if_exists"] = (["rename", "overwrite", "skip"], {
                    "default": "rename",
                    "tooltip": "If the filename already exists, rename appends _001, overwrite replaces it, and skip saves nothing.",
                })
                inserted = True

        if not inserted:
            new_required["counter_source"] = (["seed", "auto"], {"default": "seed"})
            new_required["seed_counter"] = ("INT", {
                "default": 0,
                "min": 0,
                "max": 0xffffffffffffffff,
                "step": 1,
                "forceInput": True,
            })
            new_required["if_exists"] = (["rename", "overwrite", "skip"], {"default": "rename"})

        inputs["required"] = new_required
        return inputs

    @staticmethod
    def _resolve_image_collision(image_path, if_exists="rename"):
        if not os.path.exists(image_path) or if_exists == "overwrite":
            return image_path, True
        if if_exists == "skip":
            return image_path, False

        stem, ext = os.path.splitext(image_path)
        suffix = 1
        while True:
            candidate = f"{stem}_{suffix:03d}{ext}"
            if not os.path.exists(candidate):
                return candidate, True
            suffix += 1

    def save_images(self,
        images,
        filename_prefix,
        filename_keys,
        foldername_prefix,
        foldername_keys,
        delimiter,
        save_job_data,
        job_data_per_image,
        job_custom_text,
        save_metadata,
        counter_digits,
        counter_source="seed",
        seed_counter=0,
        if_exists="rename",
        counter_position="last",
        one_counter_per_folder=True,
        image_preview=True,
        output_ext=".webp",
        quality=75,
        negative_text_opt=None,
        positive_text_opt=None,
        extra_pnginfo=None,
        prompt=None,
    ):
        from datetime import datetime
        import folder_paths

        if not filename_prefix and not filename_keys:
            filename_prefix = self.filename_prefix
        if delimiter:
            delimiter = delimiter[0]

        filename_keys_to_extract = [item.strip() for item in filename_keys.split(",")]
        foldername_keys_to_extract = [item.strip() for item in foldername_keys.split(",")]
        timestamp = datetime.now()
        custom_filename = self.generate_custom_name(filename_keys_to_extract, filename_prefix, delimiter, prompt, timestamp)
        custom_foldername = self.generate_custom_name(foldername_keys_to_extract, foldername_prefix, delimiter, prompt, timestamp)

        i = 255. * images[0].cpu().numpy()
        img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
        resolution = f"{img.width}x{img.height}"

        try:
            full_output_folder, filename, _, _, custom_filename = folder_paths.get_save_image_path(
                custom_filename,
                self.output_dir,
                images[0].shape[1],
                images[0].shape[0],
            )
            output_path = os.path.join(full_output_folder, custom_foldername)
            os.makedirs(output_path, exist_ok=True)

            if counter_source == "seed":
                counter = int(seed_counter)
            else:
                counter = self.get_latest_counter(one_counter_per_folder, output_path, filename, counter_digits, counter_position, output_ext)

            results = []
            for image in images:
                i = 255. * image.cpu().numpy()
                img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))

                if counter_position == "last":
                    file = f"{filename}{delimiter}{counter:0{counter_digits}d}{output_ext}"
                else:
                    file = f"{counter:0{counter_digits}d}{delimiter}{filename}{output_ext}"

                image_path = os.path.join(output_path, file)
                image_path, should_save = self._resolve_image_collision(image_path, if_exists)
                file = os.path.basename(image_path)

                if should_save:
                    metadata_extra = dict(extra_pnginfo) if isinstance(extra_pnginfo, dict) else {}
                    generation_info = self.build_generation_info(
                        prompt,
                        positive_text_opt,
                        negative_text_opt,
                    )
                    if generation_info:
                        metadata_extra["parameters"] = generation_info
                    self.save_image(image_path, img, prompt, save_metadata, metadata_extra, quality)

                    if save_job_data != "disabled" and job_data_per_image:
                        self.save_job_to_json(
                            save_job_data,
                            prompt,
                            filename_prefix,
                            positive_text_opt,
                            negative_text_opt,
                            job_custom_text,
                            resolution,
                            output_path,
                            f"{file.removesuffix(output_ext)}.json",
                            timestamp,
                        )

                    subfolder = self.get_subfolder_path(image_path, self.output_dir)
                    results.append({"filename": file, "subfolder": subfolder, "type": self.type})
                counter += 1

            if save_job_data != "disabled" and not job_data_per_image:
                self.save_job_to_json(save_job_data, prompt, filename_prefix, positive_text_opt, negative_text_opt, job_custom_text, resolution, output_path, "jobs.json", timestamp)

        except OSError as e:
            print(f"SaveImageExtended error: An error occurred while creating the subfolder or saving the image: {e}")
        else:
            if not image_preview:
                results = []
            return {"ui": {"images": results}}


class ConcatImageChunks:
    """
    여러 IMAGE 입력을 받아 LIST 형태로 출력 (메모리 효율적).
    torch.cat 사용 안함 - 청크들이 한 텐서로 합쳐지지 않고 리스트로 전달.
    VHS Video Combine 같은 노드가 list 받아서 한 프레임씩 처리 가능.
    + Add Input / - Remove Input 버튼으로 동적 추가/제거.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": FlexibleOptionalInputType(type="IMAGE", data={}),
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    OUTPUT_IS_LIST = (True,)  # IMAGE를 list 형태로 출력
    FUNCTION = "concat"
    CATEGORY = "image"

    def concat(self, **kwargs):
        # chunk_ 로 시작하는 키 순서대로 정렬해서 수집
        chunk_keys = sorted(
            [k for k in kwargs.keys() if k.startswith("chunk_")],
            key=lambda k: int(k.split("_")[1]) if k.split("_")[1].isdigit() else 999
        )

        # 모든 청크의 프레임을 하나의 list로 평탄화
        # IMAGE 텐서는 (N, H, W, C) - N개 프레임의 배치
        # 각 텐서를 [(1, H, W, C), (1, H, W, C), ...] 로 쪼개서 list에 추가
        all_frames = []
        total_count = 0
        for key in chunk_keys:
            tensor = kwargs[key]
            if tensor is None:
                continue
            # 텐서가 (N, H, W, C) → N개의 (1, H, W, C) 로 분할
            n = tensor.shape[0]
            for i in range(n):
                all_frames.append(tensor[i:i+1])
            total_count += n
            print(f"[Concat Image Chunks] {key}: {n}프레임")

        print(f"[Concat Image Chunks] 총 {total_count}프레임 → list 출력")
        return (all_frames,)


class VideoSaver:
    """
    IMAGE batch + AUDIO를 한 영상 파일로 저장하는 노드.
    VHS Video Combine과 달리:
    - 파일명 뒤에 _00001 같은 번호 안 붙음
    - 오디오 합쳐서 mp4 1개만 저장 (audio/non-audio 두 개 안 만듦)
    - 이미 같은 이름 있으면 덮어쓰기 또는 스킵 선택 가능
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "output_folder": ("STRING", {"default": ""}),
                "filename": ("STRING", {"default": "output.mp4"}),
                "frame_rate": ("FLOAT", {"default": 30.0, "min": 1.0, "max": 240.0, "step": 0.01}),
                "crf": ("INT", {"default": 19, "min": 0, "max": 51, "step": 1}),
                "pix_fmt": (["yuv420p", "yuv444p", "yuv420p10le"], {"default": "yuv420p"}),
                "encoder": (["libx264", "h264_nvenc", "hevc_nvenc", "h264_qsv"], {"default": "libx264"}),
                "preset": (["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower"], {"default": "medium"}),
                "save_metadata": ("BOOLEAN", {"default": True, "label_on": "워크플로우 저장", "label_off": "메타 없음"}),
                "save_workflow_sidecar": ("BOOLEAN", {"default": False, "label_on": "워크플로우 .json 같이 저장", "label_off": "영상만", "tooltip": "영상 옆에 {파일명}.workflow.json 별도 저장. ComfyUI가 mp4 메타를 못 읽는 경우 이 .json을 드래그하면 워크플로우 100% 로드됨."}),
                "if_exists": (["overwrite", "skip", "rename"], {"default": "rename", "tooltip": "같은 이름 파일이 이미 있을 때 처리. overwrite: 덮어쓰기 / skip: 저장 안 함 / rename: 이름 뒤에 _002, _003 자동 부여"}),
            },
            "optional": {
                "images": ("IMAGE", {"tooltip": "선택 입력. images 또는 맨 아래 video 중 하나만 연결하면 됩니다."}),
                "preview_autoplay": ("BOOLEAN", {"default": True}),
                "audio": ("AUDIO",),
                "trim_start_frames": ("INT", {"default": 0, "min": 0, "max": 100000, "step": 1, "tooltip": "저장 전 앞에서 잘라낼 프레임 수"}),
                "trim_end_frames": ("INT", {"default": 0, "min": 0, "max": 100000, "step": 1, "tooltip": "저장 전 뒤에서 잘라낼 프레임 수. 오버랩 청크 합칠 때는 Chunk 노드의 overlap_count 출력을 그대로 연결 (보간 배수와 무관, RIFE/FILM 같은 N→2N-1 모델 기준). 마지막 청크는 overlap_count=0이라 자동으로 안 잘림."}),
                "video": ("VIDEO", {"tooltip": "선택 입력. 연결하면 VIDEO의 프레임과 네이티브 FPS를 사용하며, 별도 audio가 없으면 포함된 오디오도 사용합니다."}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            }
        }

    RETURN_TYPES = ("STRING", "INT", "FLOAT")
    RETURN_NAMES = ("output_path", "frame_count", "saved_duration")
    FUNCTION = "save"
    CATEGORY = "video"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    def _get_ffmpeg_paths(self):
        return VideoFromFolderLoader._get_ffmpeg_paths(self)

    def save(self, output_folder, filename="output.mp4", frame_rate=30.0,
             crf=19, pix_fmt="yuv420p", encoder="libx264", preset="medium",
             save_metadata=True, save_workflow_sidecar=False, if_exists="rename",
             images=None, preview_autoplay=True, audio=None, trim_start_frames=0, trim_end_frames=0,
             video=None, prompt=None, extra_pnginfo=None):
        import subprocess as _sp
        import platform as _pf

        ffmpeg_exe, _ = self._get_ffmpeg_paths()

        if not output_folder.strip():
            raise RuntimeError("output_folder가 비어있습니다.")

        # 상대 경로면 ComfyUI output 폴더 기준으로 변환
        if not os.path.isabs(output_folder):
            try:
                import folder_paths
                base_output = folder_paths.get_output_directory()
                output_folder = os.path.join(base_output, output_folder)
            except Exception:
                # folder_paths 없으면 현재 작업 디렉토리 기준 (그대로 둠)
                output_folder = os.path.abspath(output_folder)

        os.makedirs(output_folder, exist_ok=True)

        # filename에 폴더 구분자(/, \)가 있으면 폴더 부분도 만들기
        # 그리고 안전을 위해 분리
        filename_dir, filename_base = os.path.split(filename)
        if filename_dir:
            full_dir = os.path.join(output_folder, filename_dir)
            os.makedirs(full_dir, exist_ok=True)
            output_folder = full_dir
            filename = filename_base

        # 확장자 보장
        if not filename.lower().endswith(('.mp4', '.mov', '.mkv')):
            filename = filename + ".mp4"

        output_path = os.path.abspath(os.path.join(output_folder, filename))

        def _preview_info(path):
            info = {
                "filename": os.path.basename(path),
                "subfolder": "",
                "type": "output",
                "format": "video/mp4",
                "fullpath": path,
                "autoplay": bool(preview_autoplay),
            }
            try:
                import folder_paths
                base_output = os.path.abspath(folder_paths.get_output_directory())
                rel = os.path.relpath(os.path.abspath(path), base_output)
                if not rel.startswith(".."):
                    info["filename"] = os.path.basename(rel)
                    info["subfolder"] = os.path.dirname(rel).replace(os.sep, "/")
            except Exception:
                pass
            return info

        def _return_result(path, frame_count=0, saved_duration=0.0):
            return {"ui": {"gifs": [_preview_info(path)]}, "result": (path, int(frame_count), float(saved_duration))}

        def _audio_waveform_to_samples_channels(wf):
            wf_cpu = wf.detach().float().cpu()
            if wf_cpu.dim() == 3:
                wf_cpu = wf_cpu[0]
            if wf_cpu.dim() == 1:
                return wf_cpu.numpy().reshape(-1, 1)
            if wf_cpu.dim() != 2:
                raise ValueError(f"unsupported audio waveform shape: {tuple(wf.shape)}")

            if wf_cpu.shape[0] <= 8 and wf_cpu.shape[1] > wf_cpu.shape[0]:
                return wf_cpu.transpose(0, 1).numpy()
            if wf_cpu.shape[1] <= 8 and wf_cpu.shape[0] > wf_cpu.shape[1]:
                return wf_cpu.numpy()
            return wf_cpu.transpose(0, 1).numpy()

        if os.path.exists(output_path):
            if if_exists == "skip":
                print(f"[Video Saver] 이미 존재 (skip): {output_path}")
                return _return_result(output_path)
            elif if_exists == "rename":
                # _002, _003... 부여 (첫 충돌이 _002)
                base, ext = os.path.splitext(output_path)
                counter = 2
                while True:
                    new_path = f"{base}_{counter:03d}{ext}"
                    if not os.path.exists(new_path):
                        output_path = new_path
                        break
                    counter += 1
                    if counter > 9999:
                        raise RuntimeError(f"이름 충돌 회피 한계 초과 (_002 ~ _9999): {base}{ext}")
                print(f"[Video Saver] 이름 충돌 → 자동 부여: {output_path}")
            else:  # overwrite
                print(f"[Video Saver] 덮어쓰기: {output_path}")

        # VIDEO가 연결되면 그 안의 프레임/네이티브 FPS를 우선 사용한다.
        # 별도 AUDIO 입력은 VIDEO에 포함된 오디오보다 우선한다.
        if video is not None:
            try:
                components = video.get_components()
                images = components.images
                frame_rate = float(components.frame_rate)
                if audio is None and components.audio is not None:
                    audio = components.audio
                print(f"[Video Saver] VIDEO 입력 사용: native_fps={frame_rate}")
            except Exception as e:
                raise RuntimeError(f"VIDEO 입력을 읽지 못했습니다: {e}") from e

        # IMAGE 텐서: (N, H, W, C), float [0, 1]
        if images is None or len(images) == 0:
            raise RuntimeError("images와 video 입력이 모두 비어있습니다.")

        # trim_start_frames / trim_end_frames 적용 (오버랩 청크 보간 후 접합부 정리용)
        if trim_start_frames > 0 or trim_end_frames > 0:
            original_N = images.shape[0]
            start = max(0, trim_start_frames)
            end = original_N - max(0, trim_end_frames)
            if end <= start:
                raise RuntimeError(f"trim 후 프레임이 0개 또는 음수: 원본 {original_N}, trim_start={trim_start_frames}, trim_end={trim_end_frames}")
            images = images[start:end]
            print(f"[Video Saver] trim 적용: 원본 {original_N}프레임 → {images.shape[0]}프레임 (start={start}, end_cut={trim_end_frames})")
            # 오디오도 같은 시간 비율로 자르기 (영상-오디오 싱크 유지)
            if audio is not None:
                try:
                    wf = audio.get("waveform")
                    sr = audio.get("sample_rate", 44100)
                    if wf is not None and wf.numel() > 2:
                        # 영상 길이 (초) 기준으로 오디오 trim
                        start_t = start / frame_rate
                        end_t = end / frame_rate
                        start_sample = int(start_t * sr)
                        end_sample = int(end_t * sr)
                        if wf.dim() == 3:
                            # (B, C, T)
                            wf_trimmed = wf[:, :, start_sample:end_sample]
                        elif wf.dim() == 2:
                            # (C, T)
                            wf_trimmed = wf[:, start_sample:end_sample]
                        else:
                            wf_trimmed = wf[start_sample:end_sample]
                        if wf_trimmed.numel() > 2:
                            audio = {"waveform": wf_trimmed, "sample_rate": sr}
                            print(f"[Video Saver] 오디오 trim: 샘플 [{start_sample}~{end_sample}]")
                except Exception as e:
                    print(f"[Video Saver] 오디오 trim 실패 (원본 유지): {e}")

        N, H, W, C = images.shape
        saved_duration = float(N) / float(frame_rate) if float(frame_rate) > 0 else 0.0
        print(f"[Video Saver] frame_count={N}, frame_rate={frame_rate}, saved_duration={saved_duration:.3f}s")
        print(f"[Video Saver] {N}프레임 {W}x{H} → {output_path}")

        # 오디오 처리: 임시 wav로 저장
        audio_temp_path = None
        has_audio = False
        if audio is not None:
            try:
                wf = audio.get("waveform")
                sr = audio.get("sample_rate", 44100)
                if wf is not None and wf.numel() > 2:
                    has_audio = True
                    # (B, C, T) → (C, T) → (T, C)
                    wf_np = _audio_waveform_to_samples_channels(wf)

                    # int16으로 변환해서 wav 저장
                    import wave
                    import tempfile as _tf
                    audio_temp_path = _tf.mktemp(suffix=".wav")
                    pcm = (wf_np.clip(-1.0, 1.0) * 32767.0).astype(np.int16)
                    nchannels = pcm.shape[1] if pcm.ndim > 1 else 1
                    if nchannels < 1 or nchannels > 8:
                        raise ValueError(f"invalid interpreted audio channel count: {nchannels}, waveform shape={tuple(wf.shape)}")
                    with wave.open(audio_temp_path, 'wb') as wfile:
                        wfile.setnchannels(nchannels)
                        wfile.setsampwidth(2)
                        wfile.setframerate(int(sr))
                        wfile.writeframes(pcm.tobytes())
                    print(f"[Video Saver] 오디오 임시저장: {sr}Hz, {nchannels}ch")
            except Exception as e:
                print(f"[Video Saver] 오디오 처리 실패 (무음으로 저장): {e}")
                has_audio = False

        # 워크플로우 메타데이터: VHS Video Combine과 같은 방식으로 박음
        # - 'workflow' 키: extra_pnginfo의 workflow JSON (ComfyUI가 영상 드래그 시 읽는 키)
        # - 'prompt' 키: prompt JSON
        # - 인코딩 후 별도 -c copy 패스로 박음 (v46 방식이 가장 안전)
        _meta_pairs = None  # [(key, value_str), ...]
        if save_metadata:
            try:
                import json as _json
                pairs = []
                if prompt is not None:
                    # prompt가 dict면 직렬화, str이면 그대로 (이중 직렬화 방지)
                    if isinstance(prompt, str):
                        pairs.append(("prompt", prompt))
                    else:
                        pairs.append(("prompt", _json.dumps(prompt)))
                if extra_pnginfo is not None and isinstance(extra_pnginfo, dict):
                    # extra_pnginfo는 보통 {"workflow": {...}} 형태. workflow 외 다른 키도 있을 수 있음
                    for k, v in extra_pnginfo.items():
                        if isinstance(v, str):
                            pairs.append((k, v))
                        else:
                            pairs.append((k, _json.dumps(v)))
                if pairs:
                    _meta_pairs = pairs
            except Exception as e:
                print(f"[Video Saver] 메타데이터 직렬화 실패 (건너뜀): {e}")

        # ffmpeg 명령: stdin(영상) + 선택적으로 audio 파일
        cmd = [
            ffmpeg_exe, "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{W}x{H}",
            "-r", str(frame_rate),
            "-i", "-",  # input 0: 영상 stdin
        ]
        if has_audio:
            cmd += ["-i", audio_temp_path]

        # 인코더별 설정 - NVENC는 crf 대신 cq, preset 명칭도 다름
        if encoder in ("h264_nvenc", "hevc_nvenc"):
            nvenc_preset_map = {
                "ultrafast": "p1", "superfast": "p1", "veryfast": "p2",
                "faster": "p3", "fast": "p4", "medium": "p5",
                "slow": "p6", "slower": "p7"
            }
            nvenc_preset = nvenc_preset_map.get(preset, "p5")
            cmd += [
                "-c:v", encoder,
                "-pix_fmt", pix_fmt,
                "-preset", nvenc_preset,
                "-cq", str(crf),
                "-rc", "vbr",
            ]
        elif encoder == "h264_qsv":
            cmd += [
                "-c:v", encoder,
                "-pix_fmt", pix_fmt,
                "-preset", preset,
                "-global_quality", str(crf),
            ]
        else:
            cmd += [
                "-c:v", encoder,
                "-pix_fmt", pix_fmt,
                "-crf", str(crf),
                "-preset", preset,
            ]
        if has_audio:
            # Keep the container duration pinned to the actual image batch.
            # Without this, longer audio makes players hold the last video frame.
            video_duration = max(0.001, saved_duration)
            cmd += ["-t", f"{video_duration:.6f}", "-c:a", "aac", "-b:a", "192k"]

        cmd += [output_path]

        # 프레임을 uint8 rgb24 raw bytes로 변환
        # (N, H, W, C) float[0,1] → (N, H, W, C) uint8
        proc = None
        try:
            # stderr를 PIPE로 두면 버퍼 차서 데드락. stdout은 안 씀.
            # stderr는 별도 스레드로 비우면서 마지막 N줄만 보관 (에러 메시지용)
            import threading
            from collections import deque

            popen_kw = {"stdin": _sp.PIPE, "stdout": _sp.DEVNULL, "stderr": _sp.PIPE}
            if _pf.system() == "Windows":
                si = _sp.STARTUPINFO()
                si.dwFlags |= _sp.STARTF_USESHOWWINDOW
                popen_kw["startupinfo"] = si

            proc = _sp.Popen(cmd, **popen_kw)

            # stderr drain 스레드 - 버퍼 안 차게 계속 읽음
            stderr_buf = deque(maxlen=200)
            def _drain_stderr(pipe, buf):
                try:
                    for line in iter(pipe.readline, b''):
                        if not line:
                            break
                        buf.append(line.decode('utf-8', errors='ignore').rstrip())
                except Exception:
                    pass
            stderr_thread = threading.Thread(target=_drain_stderr, args=(proc.stderr, stderr_buf), daemon=True)
            stderr_thread.start()

            # ProgressBar
            try:
                from comfy.utils import ProgressBar
                pbar = ProgressBar(N)
            except Exception:
                pbar = None

            # Producer/Consumer: GPU 변환과 stdin write를 병렬화
            # producer 스레드: GPU clamp/scale/uint8/cpu/numpy/tobytes → queue.put
            # main 스레드(consumer): queue.get → proc.stdin.write
            # bounded queue(maxsize=4)로 메모리 폭증 방지 (자동 backpressure)
            import queue as _queue
            write_error = None
            _gpu = images.is_cuda if hasattr(images, 'is_cuda') else False
            frame_size_bytes = H * W * 3
            CHUNK = max(1, min(32, (16 * 1024 * 1024) // frame_size_bytes))

            write_queue = _queue.Queue(maxsize=4)
            producer_error = [None]

            def _producer():
                try:
                    for chunk_start in range(0, N, CHUNK):
                        chunk_end = min(chunk_start + CHUNK, N)
                        chunk = images[chunk_start:chunk_end]
                        # clamp → 0-255 → uint8 (GPU에서 가능하면)
                        chunk_u8 = (chunk.clamp(0.0, 1.0) * 255.0).to(torch.uint8)
                        if chunk_u8.is_cuda:
                            chunk_u8 = chunk_u8.cpu()
                        # contiguous + numpy 변환 + bytes
                        data = chunk_u8.contiguous().numpy().tobytes()
                        write_queue.put((chunk_start, chunk_end, data))
                        del chunk_u8
                    write_queue.put(None)  # 종료 시그널
                except Exception as e:
                    producer_error[0] = e
                    try:
                        write_queue.put(None)
                    except Exception:
                        pass

            producer_thread = threading.Thread(target=_producer, daemon=True)
            producer_thread.start()

            try:
                import time as _time
                _t_write_start = _time.time()
                while True:
                    item = write_queue.get()
                    if item is None:
                        break
                    chunk_start, chunk_end, data = item
                    try:
                        proc.stdin.write(data)
                    except BrokenPipeError as e:
                        write_error = f"BrokenPipe at frame {chunk_start}: {e}"
                        # producer가 큐에 더 못 넣게 큐 비우기
                        try:
                            while True:
                                write_queue.get_nowait()
                        except Exception:
                            pass
                        break
                    if pbar is not None:
                        pbar.update(chunk_end - chunk_start)
                producer_thread.join(timeout=5.0)
                if producer_error[0] is not None:
                    raise producer_error[0]
                print(f"[Video Saver] stdin 쓰기 완료 ({_time.time()-_t_write_start:.1f}초, 변환·write 병렬)")
            finally:
                try:
                    proc.stdin.close()
                except Exception:
                    pass

            # ffmpeg 종료 대기
            proc.wait()
            stderr_thread.join(timeout=2.0)

            if proc.returncode != 0:
                err = "\n".join(list(stderr_buf)[-30:])
                msg = f"ffmpeg 실패 (returncode={proc.returncode})"
                if write_error:
                    msg += f", {write_error}"
                raise RuntimeError(f"{msg}\n--- ffmpeg stderr ---\n{err}")
            if write_error:
                err = "\n".join(list(stderr_buf)[-30:])
                print(f"[Video Saver] ffmpeg가 먼저 입력을 닫음({write_error}); returncode=0이라 저장 성공으로 처리합니다.\n--- ffmpeg stderr ---\n{err}")

            print(f"[Video Saver] ✅ 영상 저장 완료: {output_path}")

            # 두 번째 패스: 워크플로우 메타데이터를 -c copy로 박기 (VHS 호환 키로)
            if _meta_pairs:
                try:
                    import tempfile as _tf
                    meta_file = _tf.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
                    meta_file.write(";FFMETADATA1\n")
                    # FFmetadata 이스케이프: \, =, ;, #, \n
                    for k, v in _meta_pairs:
                        escaped = v.replace('\\', '\\\\').replace('=', '\\=').replace(';', '\\;').replace('#', '\\#').replace('\n', '\\\n')
                        meta_file.write(f"{k}={escaped}\n")
                    meta_file.close()

                    temp_with_meta = output_path + ".meta_tmp" + os.path.splitext(output_path)[1]
                    meta_cmd = [
                        ffmpeg_exe, "-y",
                        "-i", output_path,
                        "-f", "ffmetadata", "-i", meta_file.name,
                        "-map_metadata", "1",
                        "-c", "copy",
                    ]
                    # mp4/mov는 -movflags +use_metadata_tags로 비표준 키(workflow, prompt) 보존
                    out_ext = os.path.splitext(output_path)[1].lower()
                    if out_ext in ('.mp4', '.mov', '.m4v'):
                        meta_cmd += ["-movflags", "+use_metadata_tags"]
                    meta_cmd += [temp_with_meta]
                    meta_kw = {"capture_output": True}
                    if _pf.system() == "Windows":
                        msi = _sp.STARTUPINFO()
                        msi.dwFlags |= _sp.STARTF_USESHOWWINDOW
                        meta_kw["startupinfo"] = msi
                    meta_proc = _sp.run(meta_cmd, **meta_kw)
                    if meta_proc.returncode == 0:
                        os.remove(output_path)
                        os.rename(temp_with_meta, output_path)
                        total_bytes = sum(len(v) for _, v in _meta_pairs)
                        keys_str = ", ".join(k for k, _ in _meta_pairs)
                        print(f"[Video Saver] 워크플로우 메타데이터 박기 완료 (키: {keys_str}, 총 {total_bytes} bytes)")
                    else:
                        err = meta_proc.stderr.decode('utf-8', errors='ignore') if meta_proc.stderr else ""
                        print(f"[Video Saver] 메타데이터 박기 실패 (영상은 정상 저장됨): {err[:300]}")
                        if os.path.exists(temp_with_meta):
                            try: os.remove(temp_with_meta)
                            except: pass
                    try:
                        os.unlink(meta_file.name)
                    except Exception:
                        pass
                except Exception as e:
                    print(f"[Video Saver] 메타데이터 박기 중 오류 (영상은 정상 저장됨): {e}")

            # save_workflow_sidecar: 영상 옆에 워크플로우 .json 파일 별도 저장
            # ComfyUI가 mp4 메타를 못 읽는 경우의 백업. .json을 드래그하면 워크플로우 100% 로드됨.
            if save_workflow_sidecar and _meta_pairs:
                try:
                    import json as _json
                    # ComfyUI 워크플로우 .json 표준 형식 = workflow 키의 값 자체
                    sidecar_data = None
                    for k, v in _meta_pairs:
                        if k == "workflow":
                            # 이미 JSON 직렬화된 문자열 → parse해서 dict로
                            try:
                                sidecar_data = _json.loads(v) if isinstance(v, str) else v
                            except Exception:
                                sidecar_data = v
                            break
                    if sidecar_data is not None:
                        sidecar_path = os.path.splitext(output_path)[0] + ".workflow.json"
                        with open(sidecar_path, 'w', encoding='utf-8') as f:
                            _json.dump(sidecar_data, f, ensure_ascii=False, indent=2)
                        print(f"[Video Saver] 워크플로우 sidecar 저장: {sidecar_path}")
                except Exception as e:
                    print(f"[Video Saver] sidecar 저장 실패: {e}")
        finally:
            if proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    pass
            if audio_temp_path and os.path.exists(audio_temp_path):
                try:
                    os.remove(audio_temp_path)
                except Exception:
                    pass

        return _return_result(output_path, N, saved_duration)


class VideoConcat:
    """
    폴더 안의 영상들을 ffmpeg concat으로 합치는 노드.
    인코딩 없이 stream copy로 합치므로 빠르고 품질 손실 없음.
    같은 코덱/해상도/fps여야 함 (대부분 같은 워크플로우 출력이라 OK).
    """
    sort_methods = ["Numerical (ASC)", "Numerical (DESC)", "Alphabetical (ASC)", "Alphabetical (DESC)", "Datetime (ASC)", "Datetime (DESC)"]
    video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v']

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder_path": ("STRING", {"default": ""}),
                "output_filename": ("STRING", {"default": "concat_output.mp4"}),
            },
            "optional": {
                "filename_filter": ("STRING", {"default": ""}),
                "sort_method": (cls.sort_methods, {"default": "Numerical (ASC)"}),
                "delete_inputs_after": ("BOOLEAN", {"default": False, "label_on": "enabled", "label_off": "disabled"}),
                "trigger": (any_type,),  # 트리거용 - 다른 노드 출력을 받아 실행 순서 보장
            }
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("output_path", "video_count")
    FUNCTION = "concat"
    CATEGORY = "video"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    def _get_ffmpeg_paths(self):
        import shutil
        import platform
        node_dir = os.path.dirname(os.path.abspath(__file__))
        ffmpeg_dir = os.path.join(node_dir, "ffmpeg")
        is_windows = platform.system() == "Windows"
        ffmpeg_name = "ffmpeg.exe" if is_windows else "ffmpeg"
        ffmpeg_path = None
        for c in [os.path.join(ffmpeg_dir, ffmpeg_name), os.path.join(ffmpeg_dir, "bin", ffmpeg_name)]:
            if os.path.isfile(c):
                ffmpeg_path = c
                break
        if not ffmpeg_path:
            ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            raise RuntimeError("ffmpeg를 찾을 수 없습니다.")
        return ffmpeg_path

    def natural_key(self, s):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]

    def sort_files(self, items, base_path, method):
        def get_ts(name):
            try:
                return os.path.getmtime(os.path.join(base_path, name))
            except:
                return float('-inf')
        if method == "Alphabetical (ASC)": return sorted(items)
        elif method == "Alphabetical (DESC)": return sorted(items, reverse=True)
        elif method == "Numerical (ASC)": return sorted(items, key=self.natural_key)
        elif method == "Numerical (DESC)": return sorted(items, key=self.natural_key, reverse=True)
        elif method == "Datetime (ASC)": return sorted(items, key=get_ts)
        elif method == "Datetime (DESC)": return sorted(items, key=get_ts, reverse=True)
        else: return items

    def concat(self, folder_path, output_filename="concat_output.mp4", filename_filter="",
               sort_method="Numerical (ASC)", delete_inputs_after=False, trigger=None):
        import subprocess as _sp
        import platform as _pf
        import tempfile

        if not os.path.isdir(folder_path):
            raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {folder_path}")

        # 영상 파일 수집
        all_files = os.listdir(folder_path)
        video_files = [f for f in all_files if any(f.lower().endswith(ext) for ext in self.video_extensions)]

        # 필터 적용
        if filename_filter.strip():
            video_files = [f for f in video_files if filename_filter.strip() in f]

        if not video_files:
            raise RuntimeError(f"합칠 영상 파일이 없습니다: {folder_path}")

        # 정렬
        video_files = self.sort_files(video_files, folder_path, sort_method)
        full_paths = [os.path.join(folder_path, f) for f in video_files]

        print(f"[Video Concat] {len(full_paths)}개 영상 합치기 시작:")
        for i, p in enumerate(full_paths):
            print(f"  [{i+1}] {os.path.basename(p)}")

        # 출력 경로 결정
        if os.path.isabs(output_filename):
            output_path = output_filename
        else:
            output_path = os.path.join(folder_path, output_filename)

        # 출력이 입력 중 하나면 충돌 방지 - 임시명으로 저장 후 rename
        temp_output = output_path + ".concat_tmp.mp4"

        # concat용 텍스트 파일 생성
        list_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
        try:
            for p in full_paths:
                # ffmpeg concat demuxer 형식: file 'path' (single quote)
                escaped = p.replace("'", r"'\''").replace("\\", "/")
                list_file.write(f"file '{escaped}'\n")
            list_file.close()

            ffmpeg_exe = self._get_ffmpeg_paths()
            cmd = [
                ffmpeg_exe, "-y", "-f", "concat", "-safe", "0",
                "-i", list_file.name,
                "-c", "copy",  # stream copy - 인코딩 없음, 매우 빠름
                temp_output
            ]

            kw = {"capture_output": True}
            if _pf.system() == "Windows":
                si = _sp.STARTUPINFO()
                si.dwFlags |= _sp.STARTF_USESHOWWINDOW
                kw["startupinfo"] = si

            print(f"[Video Concat] ffmpeg 실행...")
            proc = _sp.run(cmd, **kw)

            if proc.returncode != 0:
                err = proc.stderr.decode('utf-8', errors='ignore') if proc.stderr else ""
                # stream copy 실패하면 재인코딩 시도
                print(f"[Video Concat] stream copy 실패, 재인코딩으로 재시도...")
                cmd_reencode = [
                    ffmpeg_exe, "-y", "-f", "concat", "-safe", "0",
                    "-i", list_file.name,
                    "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    temp_output
                ]
                proc2 = _sp.run(cmd_reencode, **kw)
                if proc2.returncode != 0:
                    err2 = proc2.stderr.decode('utf-8', errors='ignore') if proc2.stderr else ""
                    raise RuntimeError(f"ffmpeg concat 실패:\nstream copy: {err}\n\n재인코딩: {err2}")

            # 임시 파일을 최종 이름으로
            if os.path.exists(output_path):
                os.remove(output_path)
            os.rename(temp_output, output_path)

            print(f"[Video Concat] 완료: {output_path}")

            # 입력 영상 삭제 옵션
            if delete_inputs_after:
                for p in full_paths:
                    if os.path.abspath(p) != os.path.abspath(output_path):
                        try:
                            os.remove(p)
                            print(f"[Video Concat] 삭제됨: {os.path.basename(p)}")
                        except Exception as e:
                            print(f"[Video Concat] 삭제 실패: {p}: {e}")

        finally:
            try:
                os.unlink(list_file.name)
            except:
                pass

        return (output_path, len(full_paths))


class VideoConcatBatch:
    """
    폴더 안의 영상을 파일명 패턴으로 그룹화해서 각 그룹별로 합치는 노드.
    예) vid1_part_001.mp4, vid1_part_002.mp4, vid1_part_003.mp4 → vid1.mp4
        vid2_part_001.mp4, vid2_part_002.mp4 → vid2.mp4
    """
    sort_methods = ["Numerical (ASC)", "Numerical (DESC)", "Alphabetical (ASC)", "Alphabetical (DESC)"]
    video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v']

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder_path": ("STRING", {"default": ""}),
                "split_pattern": ("STRING", {"default": "_part_"}),
            },
            "optional": {
                "filename_filter": ("STRING", {"default": ""}),
                "output_subfolder": ("STRING", {"default": ""}),
                "output_suffix": ("STRING", {"default": ""}),
                "sort_method": (cls.sort_methods, {"default": "Numerical (ASC)"}),
                "include_subfolders": ("BOOLEAN", {"default": False, "label_on": "recursive", "label_off": "top only"}),
                "mirror_parent_folder": ("BOOLEAN", {"default": False, "label_on": "mirror parent structure", "label_off": "flat output"}),
                "delete_inputs_after": ("BOOLEAN", {"default": False, "label_on": "enabled", "label_off": "disabled"}),
                "overwrite": ("BOOLEAN", {"default": True, "label_on": "overwrite", "label_off": "skip if exists"}),
            }
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("output_folder", "groups_count")
    FUNCTION = "concat_batch"
    CATEGORY = "video"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    def _get_ffmpeg_paths(self):
        import shutil
        import platform
        node_dir = os.path.dirname(os.path.abspath(__file__))
        ffmpeg_dir = os.path.join(node_dir, "ffmpeg")
        is_windows = platform.system() == "Windows"
        ffmpeg_name = "ffmpeg.exe" if is_windows else "ffmpeg"
        ffmpeg_path = None
        for c in [os.path.join(ffmpeg_dir, ffmpeg_name), os.path.join(ffmpeg_dir, "bin", ffmpeg_name)]:
            if os.path.isfile(c):
                ffmpeg_path = c
                break
        if not ffmpeg_path:
            ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            raise RuntimeError("ffmpeg를 찾을 수 없습니다.")
        return ffmpeg_path

    def natural_key(self, s):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]

    def sort_files(self, items, method):
        if method == "Alphabetical (ASC)": return sorted(items)
        elif method == "Alphabetical (DESC)": return sorted(items, reverse=True)
        elif method == "Numerical (ASC)": return sorted(items, key=self.natural_key)
        elif method == "Numerical (DESC)": return sorted(items, key=self.natural_key, reverse=True)
        else: return items

    def concat_batch(self, folder_path, split_pattern="_part_", filename_filter="",
                     output_subfolder="", output_suffix="", sort_method="Numerical (ASC)",
                     include_subfolders=False, mirror_parent_folder=False,
                     delete_inputs_after=False, overwrite=True):
        import subprocess as _sp
        import platform as _pf
        import tempfile

        if not os.path.isdir(folder_path):
            raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {folder_path}")

        # 영상 파일 수집 (folder_path 기준 상대 경로)
        video_files = []
        if include_subfolders:
            for root, dirs, files in os.walk(folder_path):
                for f in files:
                    if any(f.lower().endswith(ext) for ext in self.video_extensions):
                        rel = os.path.relpath(os.path.join(root, f), folder_path)
                        video_files.append(rel)
            print(f"[Video Concat Batch] 서브폴더 포함 재귀 탐색: {len(video_files)}개 파일 발견")
        else:
            for f in os.listdir(folder_path):
                full = os.path.join(folder_path, f)
                if os.path.isfile(full) and any(f.lower().endswith(ext) for ext in self.video_extensions):
                    video_files.append(f)

        # filename_filter 적용 (basename 기준)
        if filename_filter.strip():
            video_files = [f for f in video_files if filename_filter.strip() in os.path.basename(f)]
            print(f"[Video Concat Batch] filter '{filename_filter.strip()}' 적용 후 {len(video_files)}개 파일")

        if not video_files:
            raise RuntimeError(f"영상 파일이 없습니다: {folder_path}")

        # 그룹화: (부모 상대 경로, base_name) 키 → 같은 폴더 내 같은 base만 같은 그룹으로
        # 다른 서브폴더에 같은 base_name이 있어도 섞이지 않음
        import re as _re
        pattern_re = _re.compile(_re.escape(split_pattern) + r'(\d+)')
        groups = {}  # (parent_rel, base_name) → [rel_path, ...]
        ungrouped = []
        for rel in video_files:
            parent_rel = os.path.dirname(rel)  # 빈 문자열이면 folder_path 직속
            basename = os.path.basename(rel)
            name_no_ext = os.path.splitext(basename)[0]
            matches = list(pattern_re.finditer(name_no_ext))
            if matches:
                last_match = matches[-1]
                base = name_no_ext[:last_match.start()]
                groups.setdefault((parent_rel, base), []).append(rel)
            else:
                ungrouped.append(rel)

        if ungrouped:
            print(f"[Video Concat Batch] {len(ungrouped)}개 파일은 split_pattern '{split_pattern}+숫자' 매칭 안됨 (스킵):")
            for u in ungrouped[:5]:
                print(f"    - {u}")
            if len(ungrouped) > 5:
                print(f"    ... 외 {len(ungrouped)-5}개")

        if not groups:
            raise RuntimeError(f"split_pattern '{split_pattern}+숫자' 패턴이 있는 파일이 없습니다.")

        # 출력 베이스 폴더 결정
        if output_subfolder.strip():
            if os.path.isabs(output_subfolder):
                output_base = output_subfolder
            else:
                output_base = os.path.join(folder_path, output_subfolder)
        else:
            output_base = folder_path

        ffmpeg_exe = self._get_ffmpeg_paths()
        success_count = 0
        skip_count = 0

        print(f"[Video Concat Batch] {len(groups)}개 그룹 발견 (mirror_parent_folder={mirror_parent_folder}):")
        for key in sorted(groups.keys()):
            parent_rel, base_name = key
            files_rel = self.sort_files(groups[key], sort_method)

            # mirror_parent_folder=True면 영상이 있던 상대 폴더 구조를 출력에도 반영
            if mirror_parent_folder and parent_rel:
                this_output_dir = os.path.join(output_base, parent_rel)
            else:
                this_output_dir = output_base
            os.makedirs(this_output_dir, exist_ok=True)

            # 출력 파일 이름 결정 (첫 파일의 확장자 사용)
            first_ext = os.path.splitext(files_rel[0])[1]
            output_name = f"{base_name}{output_suffix}{first_ext}"
            output_path = os.path.join(this_output_dir, output_name)

            display_group = base_name if not parent_rel else f"{parent_rel}/{base_name}"
            print(f"\n  그룹 [{display_group}] - {len(files_rel)}개 파일 → {output_path}")
            for f in files_rel:
                print(f"    - {f}")

            if os.path.exists(output_path) and not overwrite:
                print(f"  ⏭️ 이미 존재 (skip): {output_path}")
                skip_count += 1
                continue

            # 입력 파일과 출력 파일이 같은 경로면 임시명 사용
            temp_output = output_path + ".concat_tmp" + first_ext

            # concat 리스트 파일 생성
            list_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
            try:
                for f_rel in files_rel:
                    full_p = os.path.join(folder_path, f_rel)
                    escaped = full_p.replace("'", r"'\''").replace("\\", "/")
                    list_file.write(f"file '{escaped}'\n")
                list_file.close()

                cmd = [
                    ffmpeg_exe, "-y", "-f", "concat", "-safe", "0",
                    "-i", list_file.name,
                    "-c", "copy",
                    temp_output
                ]

                kw = {"capture_output": True}
                if _pf.system() == "Windows":
                    si = _sp.STARTUPINFO()
                    si.dwFlags |= _sp.STARTF_USESHOWWINDOW
                    kw["startupinfo"] = si

                proc = _sp.run(cmd, **kw)
                if proc.returncode != 0:
                    # 재인코딩 fallback
                    err = proc.stderr.decode('utf-8', errors='ignore') if proc.stderr else ""
                    print(f"  ⚠️ stream copy 실패, 재인코딩 시도...")
                    cmd_re = [
                        ffmpeg_exe, "-y", "-f", "concat", "-safe", "0",
                        "-i", list_file.name,
                        "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p",
                        "-c:a", "aac",
                        temp_output
                    ]
                    proc2 = _sp.run(cmd_re, **kw)
                    if proc2.returncode != 0:
                        err2 = proc2.stderr.decode('utf-8', errors='ignore') if proc2.stderr else ""
                        print(f"  ❌ 실패:\n    stream copy: {err}\n    재인코딩: {err2}")
                        continue

                if os.path.exists(output_path):
                    os.remove(output_path)
                os.rename(temp_output, output_path)
                print(f"  ✅ 완료: {output_path}")
                success_count += 1

                if delete_inputs_after:
                    for f_rel in files_rel:
                        p = os.path.join(folder_path, f_rel)
                        if os.path.abspath(p) != os.path.abspath(output_path):
                            try:
                                os.remove(p)
                                print(f"    🗑️ 삭제됨: {f_rel}")
                            except Exception as e:
                                print(f"    ⚠️ 삭제 실패: {f_rel}: {e}")

            finally:
                try:
                    os.unlink(list_file.name)
                except:
                    pass

        print(f"\n[Video Concat Batch] 전체 완료: 성공 {success_count}개, 스킵 {skip_count}개, 그룹 총 {len(groups)}개")
        return (output_base, len(groups))


class VideoLoopPlanner:
    """
    영상 반복 생성용 회차/파일명 계획 노드.
    ComfyUI의 Queue batch에서 seed를 1씩 증가시키며 쓰는 것을 기준으로 한다.
    """
    image_extensions = ['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif']
    video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v']
    sort_methods = ["Numerical (ASC)", "Numerical (DESC)", "Alphabetical (ASC)", "Alphabetical (DESC)", "Datetime (ASC)", "Datetime (DESC)"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "loop_enabled": ("BOOLEAN", {"default": True, "label_on": "loop enabled", "label_off": "loop disabled"}),
                "extension_enabled": ("BOOLEAN", {"default": False, "label_on": "extension enabled", "label_off": "extension disabled"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "source_seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "repeat_count": ("INT", {"default": 3, "min": 1, "max": 10000}),
                "output_folder": ("STRING", {"default": "LTX/loop_parts"}),
                "part_number_folders": ("BOOLEAN", {"default": True}),
                "base_filename": ("STRING", {"default": "loop"}),
                "use_source_filename": ("BOOLEAN", {"default": False}),
                "image_folder": ("STRING", {"default": ""}),
                "extension_video_folder": ("STRING", {"default": ""}),
                "load_source_image": ("BOOLEAN", {"default": False}),
                "include_subfolders": ("BOOLEAN", {"default": False}),
                "sort_method": (cls.sort_methods, {"default": "Numerical (ASC)"}),
                "final_filename": ("STRING", {"default": "loop_final.mp4"}),
                "source_index_start": ("INT", {"default": 0, "min": 0, "max": 1000000}),
                "index_start": ("INT", {"default": 1, "min": 0, "max": 1000000}),
                "digits": ("INT", {"default": 3, "min": 1, "max": 8}),
            },
            "optional": {
                "source_filename": ("STRING", {"default": ""}),
                "repeat_bool_mode": (["first", "last"], {"default": "first"}),
                "load_guide_media": ("BOOLEAN", {"default": False, "label_on": "guide media enabled", "label_off": "guide media disabled"}),
            }
        }

    # New outputs must only be appended. Existing workflows connect outputs by index.
    RETURN_TYPES = ("INT", "INT", "BOOLEAN", "BOOLEAN", "STRING", "STRING", "STRING", "STRING", "STRING", any_type, "INT", "IMAGE", "STRING", "STRING", "BOOLEAN", "BOOLEAN", "IMAGE", "AUDIO")
    RETURN_NAMES = ("iteration", "repeat_count", "is_first", "is_last", "part_filename", "previous_video_path", "current_video_path", "output_folder", "final_filename", "loop_config", "source_index", "source_image", "source_filename", "source_path", "is_repeat_first", "is_extension_mode", "source_video", "source_audio")
    FUNCTION = "plan"
    CATEGORY = "video/loop"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    def _resolve_output_folder(self, output_folder):
        if not output_folder.strip():
            raise RuntimeError("output_folder가 비어 있습니다.")
        if os.path.isabs(output_folder):
            return os.path.abspath(output_folder)
        try:
            import folder_paths
            return os.path.abspath(os.path.join(folder_paths.get_output_directory(), output_folder))
        except Exception:
            return os.path.abspath(output_folder)

    def _sanitize_filename(self, name):
        name = str(name).strip().replace("\\", "_").replace("/", "_")
        name = re.sub(r'[<>:"|?*]', "_", name)
        return name or "loop"

    def natural_key(self, s):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]

    def sort_files(self, items, base_path, method):
        def get_ts(name):
            try:
                return os.path.getmtime(os.path.join(base_path, name))
            except Exception:
                return float("-inf")
        if method == "Alphabetical (ASC)":
            return sorted(items)
        if method == "Alphabetical (DESC)":
            return sorted(items, reverse=True)
        if method == "Numerical (DESC)":
            return sorted(items, key=self.natural_key, reverse=True)
        if method == "Datetime (ASC)":
            return sorted(items, key=get_ts)
        if method == "Datetime (DESC)":
            return sorted(items, key=get_ts, reverse=True)
        return sorted(items, key=self.natural_key)

    def get_source_file_from_folder(self, image_folder, source_index, include_subfolders=False, sort_method="Numerical (ASC)"):
        if not image_folder or not str(image_folder).strip():
            return "", "", False
        image_folder = os.path.abspath(str(image_folder).strip())
        if not os.path.isdir(image_folder):
            print(f"[Video Loop Planner] image_folder를 찾을 수 없음: {image_folder}")
            return "", "", False

        image_files = []
        if include_subfolders:
            for root, dirs, files in os.walk(image_folder):
                for f in files:
                    if any(f.lower().endswith(ext) for ext in self.image_extensions):
                        image_files.append(os.path.relpath(os.path.join(root, f), image_folder))
        else:
            for f in os.listdir(image_folder):
                full = os.path.join(image_folder, f)
                if os.path.isfile(full) and any(f.lower().endswith(ext) for ext in self.image_extensions):
                    image_files.append(f)

        image_files = self.sort_files(image_files, image_folder, sort_method)
        if not image_files:
            print(f"[Video Loop Planner] image_folder에 이미지가 없음: {image_folder}")
            return "", "", False
        selected_index = int(source_index) % len(image_files)
        selected = image_files[selected_index]
        selected_base = os.path.splitext(os.path.basename(selected))[0]
        duplicate_base = sum(
            1 for f in image_files
            if os.path.splitext(os.path.basename(f))[0] == selected_base
        ) > 1
        wrapped_index = int(source_index) >= len(image_files)
        needs_source_tag = duplicate_base or wrapped_index
        return selected, os.path.abspath(os.path.join(image_folder, selected)), needs_source_tag

    def get_source_video_from_folder(self, video_folder, source_index, include_subfolders=False, sort_method="Numerical (ASC)"):
        if not video_folder or not str(video_folder).strip():
            return "", "", False
        video_folder = os.path.abspath(str(video_folder).strip())
        if not os.path.isdir(video_folder):
            print(f"[Video Loop Planner] extension_video_folder not found: {video_folder}")
            return "", "", False

        video_files = []
        if include_subfolders:
            for root, dirs, files in os.walk(video_folder):
                for f in files:
                    if any(f.lower().endswith(ext) for ext in self.video_extensions):
                        video_files.append(os.path.relpath(os.path.join(root, f), video_folder))
        else:
            for f in os.listdir(video_folder):
                full = os.path.join(video_folder, f)
                if os.path.isfile(full) and any(f.lower().endswith(ext) for ext in self.video_extensions):
                    video_files.append(f)

        video_files = self.sort_files(video_files, video_folder, sort_method)
        if not video_files:
            print(f"[Video Loop Planner] extension_video_folder has no videos: {video_folder}")
            return "", "", False

        selected_index = int(source_index) % len(video_files)
        selected = video_files[selected_index]
        selected_base = os.path.splitext(os.path.basename(selected))[0]
        duplicate_base = sum(
            1 for f in video_files
            if os.path.splitext(os.path.basename(f))[0] == selected_base
        ) > 1
        wrapped_index = int(source_index) >= len(video_files)
        needs_source_tag = duplicate_base or wrapped_index
        return selected, os.path.abspath(os.path.join(video_folder, selected)), needs_source_tag

    def _load_image_tensor(self, image_path):
        if not image_path or not os.path.isfile(image_path):
            return torch.zeros((1, 64, 64, 3), dtype=torch.float32)
        img = Image.open(image_path)
        img = ImageOps.exif_transpose(img).convert("RGB")
        arr = np.asarray(img).astype(np.float32) / 255.0
        return torch.from_numpy(arr)[None,]

    def _get_ffmpeg_paths(self):
        return VideoFromFolderLoader._get_ffmpeg_paths(self)

    def _probe_frame_count(self, ffprobe_exe, video_path):
        import json as _json
        import subprocess as _sp
        cmd = [
            ffprobe_exe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=nb_frames",
            "-of", "json", video_path
        ]
        try:
            proc = _sp.run(cmd, capture_output=True, timeout=30)
            if proc.returncode != 0:
                return None
            info = _json.loads(proc.stdout.decode("utf-8", errors="ignore") or "{}")
            streams = info.get("streams") or []
            nb = str(streams[0].get("nb_frames", "")) if streams else ""
            return int(nb) if nb.isdigit() and int(nb) > 0 else None
        except Exception:
            return None

    def _load_video_last_frame_tensor(self, video_path):
        if not video_path or not os.path.isfile(video_path):
            raise FileNotFoundError(f"extension source video not found: {video_path}")

        import tempfile
        import subprocess as _sp
        import platform as _pf

        ffmpeg_exe, ffprobe_exe = self._get_ffmpeg_paths()
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()

        try:
            startup = {}
            if _pf.system() == "Windows":
                si = _sp.STARTUPINFO()
                si.dwFlags |= _sp.STARTF_USESHOWWINDOW
                startup["startupinfo"] = si

            frame_count = self._probe_frame_count(ffprobe_exe, video_path)
            if frame_count:
                vf = f"select=eq(n\\,{frame_count - 1})"
                cmd = [ffmpeg_exe, "-y", "-v", "error", "-i", video_path, "-vf", vf, "-vsync", "0", "-frames:v", "1", tmp_path]
            else:
                cmd = [ffmpeg_exe, "-y", "-v", "error", "-sseof", "-0.5", "-i", video_path, "-update", "1", "-frames:v", "1", tmp_path]

            proc = _sp.run(cmd, capture_output=True, timeout=120, **startup)
            if proc.returncode != 0 or not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                err = proc.stderr.decode("utf-8", errors="ignore") if proc.stderr else ""
                raise RuntimeError(f"extension last frame extract failed: {video_path}\n{err}")
            return self._load_image_tensor(tmp_path)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    def _load_extension_guide_media(self, video_path):
        loaded = VideoFromFolderLoaderSimple().load_video(
            folder_path=os.path.dirname(os.path.abspath(video_path)),
            seed=0,
            include_subfolders=False,
            sort_method="Numerical (ASC)",
            path_output_mode="full_path",
            force_fps=24.0,
            frame_load_cap=0,
            skip_first_frames=0,
            hw_decode="auto",
            output_dtype="float32",
            exact_path=video_path,
        )
        frames, audio = loaded[0], loaded[1]

        # SVI continuation needs the tail of the previous clip at frame 0.  Feeding
        # the entire clip makes MiniMaxH3AddGuide crop from image[:guide_frames],
        # which anchors the *start* of the previous video instead.
        frame_count = int(frames.shape[0])
        svi_frame_count = 22 if frame_count >= 22 else (5 if frame_count >= 5 else 1)
        frames = frames[-svi_frame_count:].clone()

        waveform = audio.get("waveform") if isinstance(audio, dict) else None
        if waveform is None or waveform.shape[-1] <= 1:
            audio = None
        else:
            sample_rate = int(audio.get("sample_rate", 44100))
            sample_count = max(1, round(sample_rate * svi_frame_count / 24.0))
            audio = dict(audio)
            audio["waveform"] = waveform[..., -sample_count:].clone()
        return frames, audio

    def plan(self, loop_enabled=True, extension_enabled=False, seed=0, source_seed=0, repeat_count=3, output_folder="LTX/loop_parts",
             part_number_folders=True, base_filename="loop", use_source_filename=False,
             image_folder="", extension_video_folder="", load_source_image=False, include_subfolders=False,
             sort_method="Numerical (ASC)", final_filename="loop_final.mp4", source_index_start=0,
             index_start=1, digits=3, enabled=None, source_filename="", repeat_bool_mode="first",
             load_guide_media=False):
        if enabled is not None:
            loop_enabled = bool(enabled)
        extension_enabled = bool(extension_enabled)
        if extension_enabled:
            loop_enabled = False

        repeat_count = max(1, int(repeat_count))
        if extension_enabled:
            iteration = 0
            source_index = int(source_index_start) + int(seed)
            repeat_count = 1
        elif loop_enabled:
            iteration = int(seed) % repeat_count
            source_index = int(source_index_start) + (int(seed) // repeat_count)
        else:
            iteration = 0
            source_index = int(source_index_start) + int(seed)
        is_first = iteration == 0
        is_last = (iteration == repeat_count - 1) if (loop_enabled or extension_enabled) else False
        is_repeat_first_raw = bool(loop_enabled and is_first)
        is_repeat_last = bool(loop_enabled and is_last)
        is_repeat_first = bool(loop_enabled and not is_last) if repeat_bool_mode == "last" else is_repeat_first_raw

        output_folder_abs = self._resolve_output_folder(output_folder)
        os.makedirs(output_folder_abs, exist_ok=True)

        source_path = ""
        source_needs_tag = False
        supplied_source_filename = bool(str(source_filename or "").strip())
        folder_filename = ""
        if extension_enabled:
            folder_filename, source_path, source_needs_tag = self.get_source_video_from_folder(extension_video_folder, source_index, include_subfolders, sort_method)
            if not folder_filename:
                raise RuntimeError("extension_enabled가 켜졌지만 extension_video_folder에서 영상을 찾지 못했습니다.")
            if not source_filename:
                source_filename = folder_filename
        elif image_folder and (use_source_filename or load_source_image):
            folder_filename, source_path, source_needs_tag = self.get_source_file_from_folder(image_folder, source_index, include_subfolders, sort_method)
            if not source_filename:
                source_filename = folder_filename
        if supplied_source_filename and folder_filename:
            supplied_base = os.path.splitext(os.path.basename(str(source_filename).strip()))[0]
            selected_base = os.path.splitext(os.path.basename(str(folder_filename).strip()))[0]
            if supplied_base and selected_base and supplied_base.casefold() != selected_base.casefold():
                source_needs_tag = True
        source_video = None
        source_audio = None
        if extension_enabled:
            source_image = self._load_video_last_frame_tensor(source_path)
            if load_guide_media:
                source_video, source_audio = self._load_extension_guide_media(source_path)
        else:
            source_image = self._load_image_tensor(source_path) if load_source_image else torch.zeros((1, 64, 64, 3), dtype=torch.float32)
        source_base = os.path.splitext(os.path.basename(str(source_filename).strip()))[0] if source_filename else ""
        base = self._sanitize_filename(source_base if use_source_filename and source_base else base_filename)
        final_template = self._sanitize_filename(final_filename)
        if not final_template.lower().endswith((".mp4", ".mov", ".mkv")):
            final_template += ".mp4"

        ext = ".mp4"
        current_num = int(index_start) + iteration
        previous_num = int(index_start) + iteration - 1
        source_tag = f"src{source_index:0{int(digits)}d}"
        if extension_enabled:
            part_filename = f"{base}_{source_tag}_extension{ext}" if source_needs_tag else f"{base}_extension{ext}"
        else:
            part_filename = f"{base}_{source_tag}_part{current_num:0{int(digits)}d}{ext}"
        current_part_folder = output_folder_abs
        previous_part_folder = output_folder_abs
        if extension_enabled:
            current_part_folder = os.path.abspath(os.path.join(output_folder_abs, "extension"))
            previous_part_folder = current_part_folder
            os.makedirs(current_part_folder, exist_ok=True)
        elif not loop_enabled:
            current_part_folder = os.path.abspath(os.path.join(output_folder_abs, "disabled"))
            previous_part_folder = current_part_folder
            os.makedirs(current_part_folder, exist_ok=True)
        elif part_number_folders:
            current_part_folder = os.path.abspath(os.path.join(output_folder_abs, f"{current_num:0{int(digits)}d}"))
            previous_part_folder = os.path.abspath(os.path.join(output_folder_abs, f"{previous_num:0{int(digits)}d}"))
            os.makedirs(current_part_folder, exist_ok=True)

        current_video_path = os.path.abspath(os.path.join(current_part_folder, part_filename))
        previous_video_path = ""
        if extension_enabled:
            previous_video_path = source_path
        elif not is_first:
            previous_video_path = os.path.abspath(os.path.join(previous_part_folder, f"{base}_{source_tag}_part{previous_num:0{int(digits)}d}{ext}"))

        if loop_enabled and not extension_enabled and load_guide_media and not is_first and previous_video_path:
            if os.path.isfile(previous_video_path):
                source_video, source_audio = self._load_extension_guide_media(previous_video_path)
            else:
                print(f"[Video Loop Planner] previous_video_path 파일을 찾을 수 없음 (guide media 스킵): {previous_video_path}")

        final_root, final_ext = os.path.splitext(final_template)
        if extension_enabled and use_source_filename and source_base:
            final = f"{base}_{source_tag}_extension.mp4" if source_needs_tag else f"{base}_extension.mp4"
        elif use_source_filename and source_base and "{source}" not in final_template and "{index}" not in final_template:
            final = f"{base}_{source_tag}.mp4" if source_needs_tag else f"{base}.mp4"
        elif "{source}" in final_template or "{index}" in final_template:
            final = final_template.replace("{source}", source_tag).replace("{index}", str(source_index))
        else:
            final = f"{final_root}_{source_tag}{final_ext or '.mp4'}"

        part_paths = []
        for i in range(repeat_count):
            part_num = int(index_start) + i
            part_folder = output_folder_abs
            if extension_enabled:
                part_folder = os.path.abspath(os.path.join(output_folder_abs, "extension"))
                part_name = part_filename
            elif not loop_enabled:
                part_folder = os.path.abspath(os.path.join(output_folder_abs, "disabled"))
                part_name = f"{base}_{source_tag}_part{part_num:0{int(digits)}d}{ext}"
            elif part_number_folders:
                part_folder = os.path.abspath(os.path.join(output_folder_abs, f"{part_num:0{int(digits)}d}"))
                part_name = f"{base}_{source_tag}_part{part_num:0{int(digits)}d}{ext}"
            else:
                part_name = f"{base}_{source_tag}_part{part_num:0{int(digits)}d}{ext}"
            part_paths.append(os.path.abspath(os.path.join(part_folder, part_name)))

        loop_config = {
            "enabled": bool(loop_enabled or extension_enabled),
            "loop_enabled": bool(loop_enabled),
            "extension_enabled": bool(extension_enabled),
            "mode": "extension" if extension_enabled else ("loop" if loop_enabled else "disabled"),
            "source_index": source_index,
            "source_tag": source_tag,
            "iteration": iteration,
            "repeat_count": repeat_count,
            "is_first": is_first,
            "is_last": is_last,
            "is_repeat_first": is_repeat_first,
            "is_repeat_first_raw": is_repeat_first_raw,
            "is_repeat_last": is_repeat_last,
            "repeat_bool_mode": repeat_bool_mode,
            "part_filename": part_filename,
            "previous_video_path": previous_video_path,
            "current_video_path": current_video_path,
            "output_folder": output_folder_abs,
            "current_part_folder": current_part_folder,
            "part_number_folders": bool(part_number_folders),
            "part_paths": part_paths,
            "base_filename": base,
            "use_source_filename": bool(use_source_filename),
            "image_folder": image_folder,
            "extension_video_folder": extension_video_folder,
            "include_subfolders": bool(include_subfolders),
            "sort_method": sort_method,
            "source_filename": source_filename,
            "source_path": source_path,
            "source_needs_tag": bool(source_needs_tag),
            "load_guide_media": bool(load_guide_media),
            "final_filename": final,
            "index_start": int(index_start),
            "digits": int(digits),
        }

        mode = "extension" if extension_enabled else ("loop" if loop_enabled else "disabled")
        print(f"[Video Loop Planner] {mode}, source {source_index}, iteration {iteration + 1}/{repeat_count}: {part_filename}")
        return (iteration, repeat_count, is_first, is_last, part_filename,
                previous_video_path, current_video_path, current_part_folder, final, loop_config,
                source_index, source_image, source_filename, source_path, is_repeat_first, bool(extension_enabled),
                source_video, source_audio)


class VideoLoopSourceFilename:
    """
    Load Image From Folder에서 나온 파일명을 loop_config에 적용한다.
    Planner가 source_index를 만들고, 이미지 로더가 그 index로 파일명을 만든 뒤 이 노드에서 파일명을 확정한다.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "loop_config": (any_type,),
                "source_filename": ("STRING", {"default": ""}),
                "use_source_filename": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = (any_type, "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("loop_config", "part_filename", "previous_video_path", "current_video_path", "output_folder", "final_filename")
    FUNCTION = "apply_filename"
    CATEGORY = "video/loop"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    def _sanitize_filename(self, name):
        name = str(name).strip().replace("\\", "_").replace("/", "_")
        name = re.sub(r'[<>:"|?*]', "_", name)
        return name or "loop"

    def apply_filename(self, loop_config, source_filename="", use_source_filename=True):
        if not isinstance(loop_config, dict):
            raise RuntimeError("loop_config 입력이 필요합니다.")

        cfg = dict(loop_config)
        output_folder = cfg.get("output_folder", "")
        if not output_folder:
            raise RuntimeError("loop_config에 output_folder가 없습니다.")

        if cfg.get("extension_enabled", False):
            if source_filename:
                source_base = os.path.splitext(os.path.basename(str(source_filename).strip()))[0]
                if use_source_filename and source_base:
                    base = self._sanitize_filename(source_base)
                    digits = int(cfg.get("digits", 3))
                    source_tag = cfg.get("source_tag", f"src{int(cfg.get('source_index', 0)):0{digits}d}")
                    source_needs_tag = bool(cfg.get("source_needs_tag", False))
                    part_filename = f"{base}_{source_tag}_extension.mp4" if source_needs_tag else f"{base}_extension.mp4"
                    current_part_folder = cfg.get("current_part_folder", os.path.join(output_folder, "extension"))
                    current_video_path = os.path.abspath(os.path.join(current_part_folder, part_filename))
                    cfg.update({
                        "base_filename": base,
                        "source_filename": source_filename,
                        "part_filename": part_filename,
                        "current_video_path": current_video_path,
                        "final_filename": part_filename,
                        "part_paths": [current_video_path],
                    })
            return (
                cfg,
                cfg.get("part_filename", ""),
                cfg.get("previous_video_path", ""),
                cfg.get("current_video_path", ""),
                cfg.get("current_part_folder", output_folder),
                cfg.get("final_filename", ""),
            )

        iteration = int(cfg.get("iteration", 0))
        repeat_count = int(cfg.get("repeat_count", 1))
        index_start = int(cfg.get("index_start", 1))
        digits = int(cfg.get("digits", 3))
        source_tag = cfg.get("source_tag", f"src{int(cfg.get('source_index', 0)):0{digits}d}")
        loop_enabled = bool(cfg.get("loop_enabled", cfg.get("enabled", True)))
        part_number_folders = bool(cfg.get("part_number_folders", False))

        def part_folder_for(part_num):
            if loop_enabled and part_number_folders:
                return os.path.abspath(os.path.join(output_folder, f"{int(part_num):0{digits}d}"))
            if not loop_enabled:
                return os.path.abspath(os.path.join(output_folder, "disabled"))
            return os.path.abspath(output_folder)

        source_base = os.path.splitext(os.path.basename(str(source_filename).strip()))[0] if source_filename else ""
        if use_source_filename and source_base:
            base = self._sanitize_filename(source_base)
            source_needs_tag = bool(cfg.get("source_needs_tag", False))
            part_template = f"{base}_{source_tag}_part{{part:0{digits}d}}.mp4"
            final_filename = f"{base}_{source_tag}.mp4" if source_needs_tag else f"{base}.mp4"
        else:
            base = self._sanitize_filename(cfg.get("base_filename", "loop"))
            part_template = f"{base}_{source_tag}_part{{part:0{digits}d}}.mp4"
            final_filename = cfg.get("final_filename", f"{base}_{source_tag}.mp4")

        current_part_num = index_start + iteration
        previous_part_num = current_part_num - 1
        part_filename = part_template.format(part=current_part_num)
        current_part_folder = part_folder_for(current_part_num)
        os.makedirs(current_part_folder, exist_ok=True)
        current_video_path = os.path.abspath(os.path.join(current_part_folder, part_filename))
        previous_video_path = ""
        if not cfg.get("is_first", False):
            previous_video_path = os.path.abspath(os.path.join(part_folder_for(previous_part_num), part_template.format(part=previous_part_num)))

        part_paths = [
            os.path.abspath(os.path.join(part_folder_for(index_start + i), part_template.format(part=index_start + i)))
            for i in range(repeat_count)
        ]

        cfg.update({
            "base_filename": base,
            "source_filename": source_filename,
            "part_template": part_template,
            "part_paths": part_paths,
            "part_filename": part_filename,
            "previous_video_path": previous_video_path,
            "current_video_path": current_video_path,
            "current_part_folder": current_part_folder,
            "final_filename": final_filename,
        })

        return (cfg, part_filename, previous_video_path, current_video_path, current_part_folder, final_filename)


class VideoLoopStartFrame:
    """
    첫 회차는 initial_image를 그대로 통과시키고,
    이후 회차는 previous_video_path의 마지막 프레임 1장만 추출해서 시작 이미지로 사용한다.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "initial_image": ("IMAGE",),
                "previous_video_path": ("STRING", {"default": ""}),
                "is_first": ("BOOLEAN", {"default": True}),
                "seek_mode": (["accurate_slow", "fast_sseof"], {"default": "accurate_slow"}),
                "missing_previous": (["use_initial_image", "error"], {"default": "use_initial_image"}),
            },
            "optional": {
                "loop_config": (any_type,),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("start_image", "source_path")
    FUNCTION = "load_start_frame"
    CATEGORY = "video/loop"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    def _get_ffmpeg_paths(self):
        return VideoFromFolderLoader._get_ffmpeg_paths(self)

    def _image_to_tensor(self, image_path):
        img = Image.open(image_path)
        img = ImageOps.exif_transpose(img).convert("RGB")
        arr = np.asarray(img).astype(np.float32) / 255.0
        return torch.from_numpy(arr)[None,]

    def _probe_frame_count(self, ffprobe_exe, video_path):
        import json as _json
        import subprocess as _sp
        cmd = [
            ffprobe_exe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=nb_frames",
            "-of", "json", video_path
        ]
        try:
            proc = _sp.run(cmd, capture_output=True, timeout=30)
            if proc.returncode != 0:
                return None
            info = _json.loads(proc.stdout.decode("utf-8", errors="ignore") or "{}")
            streams = info.get("streams") or []
            nb = str(streams[0].get("nb_frames", "")) if streams else ""
            return int(nb) if nb.isdigit() and int(nb) > 0 else None
        except Exception:
            return None

    def load_start_frame(self, initial_image, previous_video_path="", is_first=True,
                         seek_mode="accurate_slow", missing_previous="use_initial_image", loop_config=None):
        if isinstance(loop_config, dict):
            enabled = loop_config.get("enabled", True)
            previous_video_path = loop_config.get("previous_video_path", previous_video_path)
            is_first = loop_config.get("is_first", is_first)
            if not enabled:
                return (initial_image, "")

        if is_first or not previous_video_path.strip():
            return (initial_image, "")
        if not os.path.isfile(previous_video_path):
            if missing_previous == "use_initial_image":
                print(f"[Video Loop Start Frame] 이전 영상 없음, 원본 이미지로 대체: {previous_video_path}")
                return (initial_image, "")
            raise FileNotFoundError(f"이전 영상 파일을 찾을 수 없습니다: {previous_video_path}")

        import tempfile
        import subprocess as _sp
        import platform as _pf

        ffmpeg_exe, ffprobe_exe = self._get_ffmpeg_paths()
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()

        try:
            startup = {}
            if _pf.system() == "Windows":
                si = _sp.STARTUPINFO()
                si.dwFlags |= _sp.STARTF_USESHOWWINDOW
                startup["startupinfo"] = si

            frame_count = self._probe_frame_count(ffprobe_exe, previous_video_path) if seek_mode == "accurate_slow" else None
            if frame_count:
                vf = f"select=eq(n\\,{frame_count - 1})"
                cmd = [ffmpeg_exe, "-y", "-v", "error", "-i", previous_video_path, "-vf", vf, "-vsync", "0", "-frames:v", "1", tmp_path]
            else:
                cmd = [ffmpeg_exe, "-y", "-v", "error", "-sseof", "-0.5", "-i", previous_video_path, "-update", "1", "-frames:v", "1", tmp_path]

            proc = _sp.run(cmd, capture_output=True, timeout=120, **startup)
            if proc.returncode != 0 or not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                err = proc.stderr.decode("utf-8", errors="ignore") if proc.stderr else ""
                raise RuntimeError(f"마지막 프레임 추출 실패: {previous_video_path}\n{err}")

            image = self._image_to_tensor(tmp_path)
            print(f"[Video Loop Start Frame] previous last frame: {previous_video_path}")
            return (image, previous_video_path)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass


class VideoLoopConcatFinal:
    """
    마지막 회차에서만 loop part 영상들을 하나로 합친다.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "is_last": ("BOOLEAN", {"default": False}),
                "output_folder": ("STRING", {"default": ""}),
                "base_filename": ("STRING", {"default": "loop"}),
                "repeat_count": ("INT", {"default": 3, "min": 1, "max": 10000}),
                "final_filename": ("STRING", {"default": "loop_final.mp4"}),
                "source_index_start": ("INT", {"default": 0, "min": 0, "max": 1000000}),
                "index_start": ("INT", {"default": 1, "min": 0, "max": 1000000}),
                "digits": ("INT", {"default": 3, "min": 1, "max": 8}),
                "overwrite": ("BOOLEAN", {"default": True}),
                "delete_parts_after": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "loop_config": (any_type,),
                "trigger": (any_type,),
                "overlap_blend_frames": ("INT", {"default": 0, "min": 0, "max": 120, "step": 1}),
            }
        }

    RETURN_TYPES = ("STRING", "INT", "BOOLEAN")
    RETURN_NAMES = ("final_video_path", "part_count", "did_concat")
    FUNCTION = "concat"
    CATEGORY = "video/loop"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    def _get_ffmpeg_paths(self):
        return VideoFromFolderLoader._get_ffmpeg_paths(self)[0]

    def _get_ffprobe_path(self):
        return VideoFromFolderLoader._get_ffmpeg_paths(self)[1]

    def _sanitize_filename(self, name):
        name = str(name).strip().replace("\\", "_").replace("/", "_")
        name = re.sub(r'[<>:"|?*]', "_", name)
        return name or "loop"

    def _probe_video_info(self, ffprobe_exe, video_path):
        import json as _json
        import subprocess as _sp

        cmd = [
            ffprobe_exe, "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", video_path
        ]
        proc = _sp.run(cmd, capture_output=True, timeout=30)
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="ignore") if proc.stderr else ""
            raise RuntimeError(f"ffprobe 실패: {video_path}\n{err}")
        info = _json.loads(proc.stdout.decode("utf-8", errors="ignore") or "{}")
        streams = info.get("streams") or []
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
        duration = video_stream.get("duration") or (info.get("format") or {}).get("duration") or 0
        try:
            duration = float(duration)
        except Exception:
            duration = 0.0
        rate = str(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "0/1")
        try:
            num, den = rate.split("/")
            fps = float(num) / float(den) if float(den) else 0.0
        except Exception:
            fps = 0.0
        return {"duration": duration, "fps": fps, "has_audio": audio_stream is not None}

    def _concat_with_overlap_blend(self, ffmpeg_exe, ffprobe_exe, part_paths, temp_output, overlap_blend_frames, startup_kwargs):
        import subprocess as _sp

        infos = [self._probe_video_info(ffprobe_exe, p) for p in part_paths]
        fps = next((i["fps"] for i in infos if i["fps"] > 0), 30.0)
        blend_seconds = max(0.001, float(overlap_blend_frames) / float(fps))
        shortest = min((i["duration"] for i in infos if i["duration"] > 0), default=0.0)
        if shortest and blend_seconds >= shortest:
            blend_seconds = max(0.001, shortest / 2.0)

        input_args = []
        for p in part_paths:
            input_args.extend(["-i", p])

        filters = []
        for i in range(len(part_paths)):
            filters.append(f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS,format=yuv420p[v{i}]")

        acc_duration = infos[0]["duration"]
        prev_label = "v0"
        for i in range(1, len(part_paths)):
            out_label = f"vx{i}"
            offset = max(0.0, acc_duration - blend_seconds)
            filters.append(
                f"[{prev_label}][v{i}]xfade=transition=fade:duration={blend_seconds:.6f}:offset={offset:.6f}[{out_label}]"
            )
            acc_duration = max(0.0, acc_duration + infos[i]["duration"] - blend_seconds)
            prev_label = out_label

        audio_label = None
        if all(i["has_audio"] for i in infos):
            for i in range(len(part_paths)):
                filters.append(f"[{i}:a]asetpts=PTS-STARTPTS[a{i}]")
            prev_audio = "a0"
            for i in range(1, len(part_paths)):
                audio_out = f"ax{i}"
                filters.append(f"[{prev_audio}][a{i}]acrossfade=d={blend_seconds:.6f}:c1=tri:c2=tri[{audio_out}]")
                prev_audio = audio_out
            audio_label = prev_audio

        filter_complex = ";".join(filters)
        cmd = [ffmpeg_exe, "-y"] + input_args + ["-filter_complex", filter_complex, "-map", f"[{prev_label}]"]
        if audio_label:
            cmd += ["-map", f"[{audio_label}]", "-c:a", "aac"]
        else:
            cmd += ["-an"]
        cmd += ["-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", temp_output]

        print(f"[Video Loop Concat Final] overlap blend {overlap_blend_frames} frames ({blend_seconds:.4f}s) 적용")
        proc = _sp.run(cmd, **startup_kwargs)
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="ignore") if proc.stderr else ""
            raise RuntimeError(f"overlap blend concat 실패:\n{err}")

    def _recover_completed_source_groups(self, output_folder, base, current_source_tag,
                                         repeat_count, index_start, digits,
                                         overlap_blend_frames, delete_parts_after):
        pattern = re.compile(
            rf"^{re.escape(base)}_(src\d+)_part(\d+)\.mp4$",
            re.IGNORECASE,
        )
        groups = {}
        for root, _, files in os.walk(output_folder):
            for name in files:
                match = pattern.match(name)
                if not match:
                    continue
                tag = match.group(1).lower()
                part_num = int(match.group(2))
                groups.setdefault(tag, {})[part_num] = os.path.abspath(os.path.join(root, name))

        expected_numbers = [int(index_start) + i for i in range(int(repeat_count))]
        recovered = 0
        for tag in sorted(groups, key=lambda value: int(re.search(r"\d+", value).group())):
            if tag.casefold() == str(current_source_tag).casefold():
                continue
            parts_by_num = groups[tag]
            if any(number not in parts_by_num for number in expected_numbers):
                continue
            recovered_final = os.path.abspath(os.path.join(output_folder, f"{base}_{tag}.mp4"))
            if os.path.isfile(recovered_final):
                continue
            source_number = int(re.search(r"\d+", tag).group())
            recovery_config = {
                "enabled": True,
                "is_last": True,
                "output_folder": output_folder,
                "base_filename": base,
                "repeat_count": int(repeat_count),
                "final_filename": f"{base}_{tag}.mp4",
                "source_index": source_number,
                "source_tag": tag,
                "index_start": int(index_start),
                "digits": int(digits),
                "part_paths": [parts_by_num[number] for number in expected_numbers],
                "source_filename": base,
                "source_path": "",
            }
            _, _, did_concat = self.concat(
                is_last=True,
                output_folder=output_folder,
                base_filename=base,
                repeat_count=repeat_count,
                final_filename=f"{base}_{tag}.mp4",
                source_index_start=source_number,
                index_start=index_start,
                digits=digits,
                overwrite=False,
                delete_parts_after=delete_parts_after,
                loop_config=recovery_config,
                overlap_blend_frames=overlap_blend_frames,
                _recover_backlog=False,
            )
            if did_concat:
                recovered += 1
        if recovered:
            print(f"[Video Loop Concat Final] recovered {recovered} previously skipped source(s)")
        return recovered

    def concat(self, is_last=False, output_folder="", base_filename="loop", repeat_count=3,
               final_filename="loop_final.mp4", source_index_start=0, index_start=1, digits=3, overwrite=True,
               delete_parts_after=False, loop_config=None, trigger=None, overlap_blend_frames=0,
               _recover_backlog=True):
        source_index = int(source_index_start)
        source_tag = f"src{source_index:0{int(digits)}d}"
        if isinstance(loop_config, dict):
            enabled = loop_config.get("enabled", True)
            is_last = loop_config.get("is_last", is_last)
            output_folder = loop_config.get("output_folder", output_folder)
            base_filename = loop_config.get("base_filename", base_filename)
            repeat_count = loop_config.get("repeat_count", repeat_count)
            final_filename = loop_config.get("final_filename", final_filename)
            source_index = loop_config.get("source_index", source_index)
            source_tag = loop_config.get("source_tag", source_tag)
            index_start = loop_config.get("index_start", index_start)
            digits = loop_config.get("digits", digits)
            part_paths_from_config = loop_config.get("part_paths")
            if not enabled:
                print("[Video Loop Concat Final] skip: planner disabled")
                return ("", 0, False)
        else:
            part_paths_from_config = None

        if not is_last:
            if isinstance(loop_config, dict):
                ready_paths = [
                    os.path.abspath(str(p))
                    for p in (loop_config.get("part_paths") or [])
                    if str(p).strip()
                ]
                missing_ready_paths = [p for p in ready_paths if not os.path.isfile(p)]
                if ready_paths and not missing_ready_paths:
                    print(
                        "[Video Loop Concat Final] is_last is false, "
                        "but all part files exist; concat anyway"
                    )
                    part_paths_from_config = ready_paths
                    is_last = True
                else:
                    print(
                        "[Video Loop Concat Final] skip: not last "
                        f"(iteration={loop_config.get('iteration')}, "
                        f"repeat_count={loop_config.get('repeat_count')}, "
                        f"source_index={loop_config.get('source_index')}, "
                        f"missing_parts={len(missing_ready_paths)})"
                    )
                    return ("", 0, False)
            else:
                print("[Video Loop Concat Final] skip: is_last is false and no loop_config")
                return ("", 0, False)
        if not os.path.isdir(output_folder):
            raise FileNotFoundError(f"output_folder를 찾을 수 없습니다: {output_folder}")

        import subprocess as _sp
        import platform as _pf
        import tempfile

        base = self._sanitize_filename(base_filename)
        final = self._sanitize_filename(final_filename)
        if not final.lower().endswith((".mp4", ".mov", ".mkv")):
            final += ".mp4"

        # Old workflows can pass one fixed source_filename (for example "ltx")
        # while the planner is actually iterating different source files. In that
        # case a shared final name would overwrite or skip every source after the
        # first one, so make the final name source-specific defensively.
        if isinstance(loop_config, dict):
            actual_source = os.path.splitext(os.path.basename(str(loop_config.get("source_path", "")).strip()))[0]
            configured_source = os.path.splitext(os.path.basename(str(loop_config.get("source_filename", "")).strip()))[0]
            final_root, final_ext = os.path.splitext(final)
            if (
                actual_source
                and configured_source
                and actual_source.casefold() != configured_source.casefold()
                and source_tag.casefold() not in final_root.casefold()
            ):
                final = f"{final_root}_{source_tag}{final_ext or '.mp4'}"
                print(f"[Video Loop Concat Final] duplicate final name corrected: {final}")

        if part_paths_from_config:
            part_paths = [os.path.abspath(str(p)) for p in part_paths_from_config]
        else:
            part_paths = [
                os.path.abspath(os.path.join(output_folder, f"{base}_{source_tag}_part{int(index_start) + i:0{int(digits)}d}.mp4"))
                for i in range(int(repeat_count))
            ]

        def find_existing_part(expected_path, part_num):
            if os.path.isfile(expected_path):
                return expected_path
            expected_name = os.path.basename(expected_path).lower()
            source_part_suffix = f"{source_tag}_part{int(part_num):0{int(digits)}d}.mp4".lower()
            loose_suffix = f"_part{int(part_num):0{int(digits)}d}.mp4".lower()
            matches = []
            for root, _, files in os.walk(output_folder):
                for name in files:
                    lower_name = name.lower()
                    if lower_name == expected_name or lower_name.endswith(source_part_suffix):
                        matches.append(os.path.abspath(os.path.join(root, name)))
                    elif source_tag and source_tag.lower() in lower_name and lower_name.endswith(loose_suffix):
                        matches.append(os.path.abspath(os.path.join(root, name)))
            matches = sorted(set(matches), key=lambda p: (len(p), p.lower()))
            return matches[0] if matches else expected_path

        resolved_part_paths = []
        for i, path in enumerate(part_paths):
            resolved_part_paths.append(find_existing_part(path, int(index_start) + i))
        part_paths = resolved_part_paths

        missing = [p for p in part_paths if not os.path.isfile(p)]
        if missing:
            raise FileNotFoundError("합칠 파트 영상이 없습니다:\n" + "\n".join(missing[:20]))

        if _recover_backlog and isinstance(loop_config, dict):
            actual_source = os.path.splitext(os.path.basename(str(loop_config.get("source_path", "")).strip()))[0]
            configured_source = os.path.splitext(os.path.basename(str(loop_config.get("source_filename", "")).strip()))[0]
            if actual_source and configured_source and actual_source.casefold() != configured_source.casefold():
                self._recover_completed_source_groups(
                    output_folder,
                    base,
                    source_tag,
                    repeat_count,
                    index_start,
                    digits,
                    overlap_blend_frames,
                    delete_parts_after,
                )

        final_path = os.path.abspath(os.path.join(output_folder, final))
        if os.path.exists(final_path) and not overwrite:
            print(f"[Video Loop Concat Final] 이미 존재해서 스킵: {final_path}")
            return (final_path, len(part_paths), False)

        ffmpeg_exe = self._get_ffmpeg_paths()
        fd, list_path = tempfile.mkstemp(suffix=".txt", text=True)
        os.close(fd)
        temp_output = final_path + ".tmp" + os.path.splitext(final_path)[1]

        try:
            with open(list_path, "w", encoding="utf-8") as f:
                for p in part_paths:
                    safe = p.replace("\\", "/").replace("'", "'\\''")
                    f.write(f"file '{safe}'\n")

            kw = {"capture_output": True}
            if _pf.system() == "Windows":
                si = _sp.STARTUPINFO()
                si.dwFlags |= _sp.STARTF_USESHOWWINDOW
                kw["startupinfo"] = si

            if overlap_blend_frames > 0 and len(part_paths) > 1:
                ffprobe_exe = self._get_ffprobe_path()
                self._concat_with_overlap_blend(
                    ffmpeg_exe, ffprobe_exe, part_paths, temp_output, overlap_blend_frames, kw
                )
                if os.path.exists(final_path):
                    os.remove(final_path)
                os.rename(temp_output, final_path)
                print(f"[Video Loop Concat Final] overlap blend 완료: {final_path}")

                if delete_parts_after:
                    for p in part_paths:
                        if os.path.abspath(p) != os.path.abspath(final_path):
                            try:
                                os.remove(p)
                            except Exception as e:
                                print(f"[Video Loop Concat Final] part delete failed: {p}: {e}")

                return (final_path, len(part_paths), True)

            cmd = [ffmpeg_exe, "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", temp_output]
            proc = _sp.run(cmd, **kw)
            if proc.returncode != 0:
                err = proc.stderr.decode("utf-8", errors="ignore") if proc.stderr else ""
                print("[Video Loop Concat Final] stream copy 실패, 재인코딩 시도")
                cmd_re = [
                    ffmpeg_exe, "-y", "-f", "concat", "-safe", "0", "-i", list_path,
                    "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", temp_output
                ]
                proc_re = _sp.run(cmd_re, **kw)
                if proc_re.returncode != 0:
                    err_re = proc_re.stderr.decode("utf-8", errors="ignore") if proc_re.stderr else ""
                    raise RuntimeError(f"최종 concat 실패:\nstream copy: {err}\n\nreencode: {err_re}")

            if os.path.exists(final_path):
                os.remove(final_path)
            os.rename(temp_output, final_path)
            print(f"[Video Loop Concat Final] 완료: {final_path}")

            if delete_parts_after:
                for p in part_paths:
                    if os.path.abspath(p) != os.path.abspath(final_path):
                        try:
                            os.remove(p)
                        except Exception as e:
                            print(f"[Video Loop Concat Final] 파트 삭제 실패: {p}: {e}")

            return (final_path, len(part_paths), True)
        finally:
            try:
                if os.path.exists(list_path):
                    os.remove(list_path)
            except Exception:
                pass
            try:
                if os.path.exists(temp_output):
                    os.remove(temp_output)
            except Exception:
                pass


class MemoryCleanupBridge:
    """
    청크 사이에 메모리를 명시적으로 비우는 다리 노드.

    사용법:
        frames_1 → Resize → VHS_Combine → MemoryCleanupBridge ──┐
                                                                 │ (bridge_out)
        frames_2 → MemoryCleanupBridge(bridge_in=위↑) → Resize → VHS_Combine → ...

    동작:
        1. trigger_in이 도착할 때까지 대기 (이전 청크 완료 보장)
        2. gc.collect() + torch.cuda.empty_cache() 호출 → RAM/VRAM 비움
        3. passthrough 값을 그대로 반환 (다음 청크가 시작할 수 있게)
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "passthrough": (any_type,),
            },
            "optional": {
                "trigger_in": (any_type,),
                "clean_ram": ("BOOLEAN", {"default": True, "label_on": "✅ RAM", "label_off": "❌ RAM"}),
                "clean_vram": ("BOOLEAN", {"default": True, "label_on": "✅ VRAM", "label_off": "❌ VRAM"}),
                "verbose": ("BOOLEAN", {"default": True, "label_on": "log", "label_off": "silent"}),
            }
        }

    RETURN_TYPES = (any_type,)
    RETURN_NAMES = ("passthrough",)
    FUNCTION = "bridge"
    CATEGORY = "memory"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")  # 항상 실행

    def bridge(self, passthrough, trigger_in=None, clean_ram=True, clean_vram=True, verbose=True):
        import gc
        import time

        ram_before = 0
        vram_before = 0

        if verbose:
            try:
                import psutil
                proc = psutil.Process(os.getpid())
                ram_before = proc.memory_info().rss / (1024 ** 3)  # GB
            except Exception:
                pass
            try:
                if torch.cuda.is_available():
                    vram_before = torch.cuda.memory_allocated() / (1024 ** 3)
            except Exception:
                pass

        # RAM 정리
        if clean_ram:
            # 여러 번 호출해서 순환 참조까지 회수
            for _ in range(3):
                gc.collect()

        # VRAM 정리
        if clean_vram:
            try:
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.ipc_collect()
            except Exception as e:
                if verbose:
                    print(f"[Memory Bridge] VRAM 정리 실패: {e}")

        # 잠깐 대기 - OS가 메모리 회수할 시간 줌
        time.sleep(0.1)

        if verbose:
            ram_after = 0
            vram_after = 0
            try:
                import psutil
                proc = psutil.Process(os.getpid())
                ram_after = proc.memory_info().rss / (1024 ** 3)
            except Exception:
                pass
            try:
                if torch.cuda.is_available():
                    vram_after = torch.cuda.memory_allocated() / (1024 ** 3)
            except Exception:
                pass
            print(f"[Memory Bridge] RAM: {ram_before:.2f}GB → {ram_after:.2f}GB ({ram_after-ram_before:+.2f}), "
                  f"VRAM: {vram_before:.2f}GB → {vram_after:.2f}GB ({vram_after-vram_before:+.2f})")

        return (passthrough,)


class VideoCompareSplit:
    """
    여러 영상을 한 화면에 분할 비교 (split-screen comparison).
    각 영역에 해당 영상의 같은 위치 부분만 보여줌 (before/after 비교용).
    
    분할 위치는 노드 UI의 캔버스에서 드래그로 조절.
    영상 입력 슬롯은 연결 상태에 따라 동적으로 늘어남.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "split_direction": (["vertical", "horizontal"], {"default": "vertical"}),
                # split_positions는 JS UI에서 드래그로 자동 업데이트됨. "0.5" 또는 "0.33,0.67" 식.
                "split_positions": ("STRING", {"default": "0.5", "multiline": False}),
                "border_width": ("INT", {"default": 2, "min": 0, "max": 30, "step": 1}),
                "border_color": ("STRING", {"default": "#FFFFFF"}),
                "length_mode": (["shortest", "longest"], {"default": "shortest"}),
                "resolution_ref": (["first", "max", "min"], {"default": "first"}),
                "resize_mode": (["fit", "crop_center"], {"default": "fit"}),
            },
            "optional": FlexibleOptionalInputType("IMAGE", {
                "image_1": ("IMAGE",),
                "image_2": ("IMAGE",),
            })
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("frames",)
    FUNCTION = "compare"
    CATEGORY = "video"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    def compare(self, split_direction="vertical", split_positions="0.5",
                border_width=2, border_color="#FFFFFF",
                length_mode="shortest", resolution_ref="first", resize_mode="fit",
                **kwargs):
        import torch.nn.functional as F

        # 영상 입력 수집 (image_N 형식, N 순서대로)
        images_list = []
        # image_1 부터 순차로 찾기 (중간에 빠진 게 있으면 거기서 중단)
        idx = 1
        while True:
            key = f"image_{idx}"
            if key in kwargs and kwargs[key] is not None:
                images_list.append(kwargs[key])
                idx += 1
            else:
                # 중간 빠짐 허용: 뒤쪽도 확인 (최대 image_32까지)
                found_later = False
                for j in range(idx + 1, 33):
                    later_key = f"image_{j}"
                    if later_key in kwargs and kwargs[later_key] is not None:
                        # 빠진 슬롯은 None을 채우지 않고 그냥 다음 영상으로 진행
                        images_list.append(kwargs[later_key])
                        idx = j + 1
                        found_later = True
                        break
                if not found_later:
                    break

        if len(images_list) == 0:
            raise RuntimeError("최소 1개 영상 입력 필요 (image_1, image_2, ...)")
        if len(images_list) == 1:
            print(f"[VideoCompareSplit] 입력 영상 1개 → 그대로 출력")
            return (images_list[0],)

        N_videos = len(images_list)

        # 분할 위치 파싱
        try:
            positions = [float(p.strip()) for p in split_positions.split(",") if p.strip()]
        except Exception:
            positions = []
        expected_positions = N_videos - 1
        if len(positions) != expected_positions:
            # 균등 분할로 자동
            positions = [(i + 1) / N_videos for i in range(expected_positions)]
            print(f"[VideoCompareSplit] split_positions 갯수 불일치 ({len(positions)} vs expected {expected_positions}) → 균등 분할로 자동: {positions}")
        positions = sorted([max(0.001, min(0.999, p)) for p in positions])

        # 해상도 결정
        if resolution_ref == "first":
            target_H, target_W = int(images_list[0].shape[1]), int(images_list[0].shape[2])
        elif resolution_ref == "max":
            target_H = max(int(img.shape[1]) for img in images_list)
            target_W = max(int(img.shape[2]) for img in images_list)
        else:  # min
            target_H = min(int(img.shape[1]) for img in images_list)
            target_W = min(int(img.shape[2]) for img in images_list)

        # 프레임 수 결정
        if length_mode == "shortest":
            target_N = min(int(img.shape[0]) for img in images_list)
        else:
            target_N = max(int(img.shape[0]) for img in images_list)

        print(f"[VideoCompareSplit] {N_videos}개 영상, {target_N}프레임, {target_W}x{target_H}, {split_direction} 분할 @ {positions}")

        # 디바이스/dtype 결정 (첫 영상 기준)
        out_device = images_list[0].device
        out_dtype = images_list[0].dtype

        # 각 영상을 target 해상도/프레임 수로 정규화
        normalized = []
        for vi, img in enumerate(images_list):
            # 디바이스/dtype 통일
            if img.device != out_device or img.dtype != out_dtype:
                img = img.to(device=out_device, dtype=out_dtype)
            N, H, W, C = img.shape
            # 해상도 리사이즈
            if H != target_H or W != target_W:
                if resize_mode == "fit":
                    img_t = img.permute(0, 3, 1, 2)  # (N, C, H, W)
                    img_t = F.interpolate(img_t, size=(target_H, target_W), mode='bilinear', align_corners=False)
                    img = img_t.permute(0, 2, 3, 1).contiguous()
                else:  # crop_center
                    # 비율 유지 리사이즈 후 중앙 크롭
                    scale = max(target_H / H, target_W / W)
                    nh, nw = int(round(H * scale)), int(round(W * scale))
                    img_t = img.permute(0, 3, 1, 2)
                    img_t = F.interpolate(img_t, size=(nh, nw), mode='bilinear', align_corners=False)
                    img = img_t.permute(0, 2, 3, 1).contiguous()
                    # 중앙 크롭
                    y0 = max(0, (nh - target_H) // 2)
                    x0 = max(0, (nw - target_W) // 2)
                    img = img[:, y0:y0 + target_H, x0:x0 + target_W, :]
            # 프레임 수 정규화
            if img.shape[0] < target_N:
                if length_mode == "longest":
                    # 마지막 프레임 복제 패딩
                    pad = img[-1:].expand(target_N - img.shape[0], -1, -1, -1)
                    img = torch.cat([img, pad], dim=0)
            img = img[:target_N]
            normalized.append(img)

        # 경계선 색 파싱 (RGB 0~1)
        try:
            hex_color = border_color.lstrip('#').strip()
            r = int(hex_color[0:2], 16) / 255.0
            g = int(hex_color[2:4], 16) / 255.0
            b = int(hex_color[4:6], 16) / 255.0
        except Exception:
            r, g, b = 1.0, 1.0, 1.0

        # 출력 텐서: 첫 영상 그대로 시작 → 다른 영역만 덮어쓰기 (메모리 절약)
        output = normalized[0].clone()

        if split_direction == "vertical":
            # 수직 분할: x축 경계
            boundaries = [0] + [int(round(p * target_W)) for p in positions] + [target_W]
            for i in range(N_videos):
                if i == 0:
                    continue  # 이미 첫 영상으로 채워짐
                x_s, x_e = boundaries[i], boundaries[i + 1]
                if x_s < x_e:
                    output[:, :, x_s:x_e, :] = normalized[i][:, :, x_s:x_e, :]
            # 경계선
            if border_width > 0:
                for pos in positions:
                    x = int(round(pos * target_W))
                    x_s = max(0, x - border_width // 2)
                    x_e = min(target_W, x_s + border_width)
                    output[:, :, x_s:x_e, 0] = r
                    output[:, :, x_s:x_e, 1] = g
                    output[:, :, x_s:x_e, 2] = b
        else:
            # 수평 분할: y축 경계
            boundaries = [0] + [int(round(p * target_H)) for p in positions] + [target_H]
            for i in range(N_videos):
                if i == 0:
                    continue
                y_s, y_e = boundaries[i], boundaries[i + 1]
                if y_s < y_e:
                    output[:, y_s:y_e, :, :] = normalized[i][:, y_s:y_e, :, :]
            if border_width > 0:
                for pos in positions:
                    y = int(round(pos * target_H))
                    y_s = max(0, y - border_width // 2)
                    y_e = min(target_H, y_s + border_width)
                    output[:, y_s:y_e, :, 0] = r
                    output[:, y_s:y_e, :, 1] = g
                    output[:, y_s:y_e, :, 2] = b

        return (output,)


class ImageMaxMinDimension:
    """
    이미지의 가로/세로 중 큰 값(max_dim)과 작은 값(min_dim)을 INT로 출력.
    영상 리사이즈할 때 긴 변/짧은 변 기준 계산에 유용.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": {
                "image": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT", "INT", "STRING")
    RETURN_NAMES = ("max_dim", "min_dim", "width", "height", "orientation")
    FUNCTION = "get_dims"
    CATEGORY = "image"

    def get_dims(self, image=None):
        if image is None or not hasattr(image, "shape") or len(image.shape) < 3:
            print("[Image Max/Min Dim] 이미지 입력 없음 - 기본값으로 통과")
            return (0, 0, 0, 0, "none")

        # IMAGE 텐서 shape: (N, H, W, C)
        h = int(image.shape[1])
        w = int(image.shape[2])
        max_dim = max(w, h)
        min_dim = min(w, h)
        if w > h:
            orientation = "landscape"
        elif h > w:
            orientation = "portrait"
        else:
            orientation = "square"
        print(f"[Image Max/Min Dim] {w}x{h} → max={max_dim}, min={min_dim}, {orientation}")
        return (max_dim, min_dim, w, h, orientation)


class LoopStableImageAutosize:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "is_first": ("BOOLEAN", {"default": True}),
                "max_size": ("INT", {"default": 1280, "min": 0, "max": 16384, "step": 8}),
                "min_size": ("INT", {"default": 720, "min": 0, "max": 16384, "step": 8}),
                "divisible_by": ("INT", {"default": 32, "min": 1, "max": 512, "step": 1}),
                "interpolation_mode": (["lanczos", "bicubic", "bilinear", "nearest"], {"default": "lanczos"}),
                "crop_mode": (["center", "disabled"], {"default": "center"}),
                "fixed_width": ("INT", {"default": 0, "min": 0, "max": 16384, "step": 8}),
                "fixed_height": ("INT", {"default": 0, "min": 0, "max": 16384, "step": 8}),
                "use_reference_when_not_first": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "reference_image": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("IMAGE", "INT", "INT", "FLOAT")
    RETURN_NAMES = ("image", "width", "height", "multiplier")
    FUNCTION = "autosize"
    CATEGORY = "image"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    def _round_to_divisible(self, value, divisible_by):
        divisible_by = max(1, int(divisible_by))
        value = max(1, int(round(float(value))))
        return max(divisible_by, int(round(value / divisible_by)) * divisible_by)

    def _calc_target(self, width, height, max_size, min_size, divisible_by):
        width = max(1, int(width))
        height = max(1, int(height))
        max_size = int(max_size)
        min_size = int(min_size)
        scale = 1.0
        if max_size > 0:
            scale = float(max_size) / float(max(width, height))
        if min_size > 0 and min(width, height) * scale < min_size:
            scale = float(min_size) / float(min(width, height))
        target_w = self._round_to_divisible(width * scale, divisible_by)
        target_h = self._round_to_divisible(height * scale, divisible_by)
        return target_w, target_h, scale

    def _resize_exact(self, image, target_w, target_h, interpolation_mode, crop_mode):
        import torch.nn.functional as F

        source_h = int(image.shape[1])
        source_w = int(image.shape[2])
        target_w = max(1, int(target_w))
        target_h = max(1, int(target_h))
        if source_w == target_w and source_h == target_h:
            return image

        mode_map = {
            "lanczos": "bicubic",
            "bicubic": "bicubic",
            "bilinear": "bilinear",
            "nearest": "nearest",
        }
        mode = mode_map.get(interpolation_mode, "bicubic")
        tensor = image.movedim(-1, 1)

        if crop_mode == "center":
            scale = max(float(target_w) / float(source_w), float(target_h) / float(source_h))
            resize_w = max(1, int(round(source_w * scale)))
            resize_h = max(1, int(round(source_h * scale)))
            kwargs = {} if mode == "nearest" else {"align_corners": False}
            resized = F.interpolate(tensor, size=(resize_h, resize_w), mode=mode, **kwargs)
            left = max(0, (resize_w - target_w) // 2)
            top = max(0, (resize_h - target_h) // 2)
            resized = resized[:, :, top:top + target_h, left:left + target_w]
        else:
            kwargs = {} if mode == "nearest" else {"align_corners": False}
            resized = F.interpolate(tensor, size=(target_h, target_w), mode=mode, **kwargs)

        return resized.movedim(1, -1).clamp(0.0, 1.0)

    def autosize(self, image, is_first=True, max_size=1280, min_size=720, divisible_by=32,
                 interpolation_mode="lanczos", crop_mode="center", fixed_width=0, fixed_height=0,
                 use_reference_when_not_first=True, reference_image=None):
        source_h = int(image.shape[1])
        source_w = int(image.shape[2])

        if is_first:
            target_w, target_h, multiplier = self._calc_target(source_w, source_h, max_size, min_size, divisible_by)
        elif int(fixed_width) > 0 and int(fixed_height) > 0:
            target_w = self._round_to_divisible(fixed_width, divisible_by)
            target_h = self._round_to_divisible(fixed_height, divisible_by)
            multiplier = float(target_w) / float(source_w) if source_w else 1.0
        elif use_reference_when_not_first and reference_image is not None and hasattr(reference_image, "shape"):
            ref_h = int(reference_image.shape[1])
            ref_w = int(reference_image.shape[2])
            target_w, target_h, multiplier = self._calc_target(ref_w, ref_h, max_size, min_size, divisible_by)
        else:
            target_w = source_w
            target_h = source_h
            multiplier = 1.0

        resized = self._resize_exact(image, target_w, target_h, interpolation_mode, crop_mode)
        print(f"[Loop Stable Image Autosize] {'first' if is_first else 'loop'} {source_w}x{source_h} -> {target_w}x{target_h}")
        return (resized, int(target_w), int(target_h), float(multiplier))


class WildcardCyclePicker:
    """
    와카 리스트에서 N 사이클마다 1개씩 선택해서 고정 출력.
    여러 개를 다른 cycle_size로 연결하면 중첩 사이클 구성 가능.
    
    예: cycle_size=13, list=[복장A, 복장B, 복장C, ...]
        seed 0~12:  복장A
        seed 13~25: 복장B
        seed 26~38: 복장C
        ...
    
    예시 워크플로우 (캐 1명 + 복장 + 장소 + action 13줄):
        - 복장 Picker (cycle_size=13): action 한 사이클마다 바뀜
        - 장소 Picker (cycle_size=130): 복장 10번 다 돌면 장소 바뀜
        - char: 그냥 텍스트 고정
        - action: WildcardCombiner의 action에 넣음
        - 모두 String Concat으로 합쳐서 사용
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "wildcard_list": ("STRING", {"multiline": True, "default": "", "tooltip": "줄바꿈으로 구분된 와카 항목. WildcardFileLoader의 wildcard_list 출력 연결 가능."}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "tooltip": "외부 seed (예: 큐 increment seed)"}),
                "cycle_size": ("INT", {"default": 1, "min": 1, "max": 1000000, "step": 1, "tooltip": "몇 번 seed 동안 같은 항목을 유지할지. action 13줄이면 13으로 두면 action 한 사이클마다 항목 바뀜."}),
                "pick_mode": (["sequential", "random"], {"default": "sequential", "tooltip": "sequential: 순서대로 / random: cycle_index를 시드로 랜덤 선택"}),
                "random_seed_offset": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "tooltip": "random 모드에서 시드 오프셋. 같은 seed로 여러 picker가 같은 항목 뽑는 거 방지."}),
            }
        }

    RETURN_TYPES = ("STRING", "INT", "INT", "INT")
    RETURN_NAMES = ("current_pick", "pick_index", "total_picks", "cycle_index")
    FUNCTION = "pick"
    CATEGORY = "image/animation"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    def pick(self, wildcard_list, seed, cycle_size, pick_mode="sequential", random_seed_offset=0):
        items = [w.strip() for w in wildcard_list.split('\n') if w.strip()]
        if not items:
            return ("", 0, 0, 0)

        cycle_size = max(1, int(cycle_size))
        cycle_idx = int(seed) // cycle_size
        total = len(items)

        if pick_mode == "random":
            rng = random.Random(cycle_idx + int(random_seed_offset))
            pick_idx = rng.randint(0, total - 1)
        else:
            pick_idx = cycle_idx % total

        current = items[pick_idx]
        print(f"[Cycle Picker] seed={seed} cycle_size={cycle_size} → cycle[{cycle_idx}] mode={pick_mode} → pick[{pick_idx+1}/{total}]: '{current[:50]}{'...' if len(current) > 50 else ''}'")
        return (current, pick_idx, total, cycle_idx)


class NaiToA1111Weight:
    """
    NovelAI 가중치 문법을 A1111/ComfyUI 가중치 문법으로 변환.
    
    NAI 문법:
      {tag}        = 1.05배 강조 (curly brace)
      [tag]        = 1/1.05배 약화 (square bracket)
      중첩 가능: {{{tag}}} = 1.05^3 ≈ 1.158
      
      N::tag::     = N배 가중치 (커스텀 확장 문법)
      예: 2::ejaculation:: → (ejaculation:2)
    
    변환 결과:
      {tag} / {{tag}} → (tag:1.05) / (tag:1.1025)
      [tag] / [[tag]] → (tag:0.9524) / (tag:0.9070)
      N::tag::       → (tag:N)
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": ""}),
                "curly_strength": ("FLOAT", {"default": 1.05, "min": 1.0, "max": 2.0, "step": 0.01, "tooltip": "{} 한 겹의 가중치. NAI 기본 1.05"}),
                "square_strength": ("FLOAT", {"default": 1.05, "min": 1.0, "max": 2.0, "step": 0.01, "tooltip": "[] 한 겹의 약화 가중치 (1/이 값). NAI 기본 1.05"}),
                "decimal_places": ("INT", {"default": 3, "min": 1, "max": 6, "step": 1, "tooltip": "변환된 가중치 소수점 자릿수"}),
                "max_weight": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 100.0, "step": 0.01, "tooltip": "0이면 제한 없음. 2로 설정하면 3::tag:: 또는 중첩 강조가 최대 2로 제한됨"}),
                "escape_parentheses": ("BOOLEAN", {"default": True, "label_on": "escape", "label_off": "keep", "tooltip": "일반 괄호를 \\( \\)로 이스케이프할지 여부"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("converted", "negative")
    FUNCTION = "convert"
    CATEGORY = "text"

    def convert(self, text, curly_strength=1.05, square_strength=1.05, decimal_places=3,
                max_weight=0.0, escape_parentheses=True):
        import re as _re

        max_weight = float(max_weight or 0.0)
        negative_tags = []

        def clamp_weight(v):
            if max_weight > 0 and v > max_weight:
                return max_weight
            return v

        def fmt(v):
            # 1.000 같은 정수 가까운 값은 정수로 떨어지면 정수로, 아니면 소수 N자리
            s = f"{v:.{decimal_places}f}"
            # 후행 0 정리 (1.050 → 1.05)
            if '.' in s:
                s = s.rstrip('0').rstrip('.')
            return s

        def add_negative_tag(tag):
            tag = str(tag).strip()
            if tag:
                negative_tags.append(tag)

        def find_unescaped_close(s, start):
            depth = 1
            i = start
            while i < len(s):
                if s[i] == '\\':
                    i += 2
                    continue
                if s[i] == '(':
                    depth += 1
                elif s[i] == ')':
                    depth -= 1
                    if depth == 0:
                        return i
                i += 1
            return -1

        def split_a1111_weight(content):
            depth = 0
            split_at = -1
            i = 0
            while i < len(content):
                if content[i] == '\\':
                    i += 2
                    continue
                if content[i] == '(':
                    depth += 1
                elif content[i] == ')' and depth > 0:
                    depth -= 1
                elif content[i] == ':' and depth == 0:
                    split_at = i
                i += 1

            if split_at < 1:
                return None

            weight = content[split_at + 1:].strip()
            if _re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', weight):
                return content[:split_at], content[split_at + 1:]
            return None

        def escape_plain_parentheses(s):
            parts = []
            i = 0
            while i < len(s):
                ch = s[i]
                if ch == '\\':
                    parts.append(s[i:i + 2])
                    i += 2
                    continue
                if ch != '(':
                    parts.append(ch)
                    i += 1
                    continue

                close = find_unescaped_close(s, i + 1)
                if close < 0:
                    parts.append(ch)
                    i += 1
                    continue

                content = s[i + 1:close]
                weighted = split_a1111_weight(content)
                if weighted:
                    tag, weight = weighted
                    if float(weight.strip()) <= 0:
                        add_negative_tag(tag)
                        parts.append("")
                    else:
                        parts.append(f"({escape_plain_parentheses(tag)}:{weight})")
                else:
                    parts.append(r"\(" if escape_parentheses else "(")
                    parts.append(escape_plain_parentheses(content))
                    parts.append(r"\)" if escape_parentheses else ")")
                i = close + 1
            return ''.join(parts)

        def cleanup_removed_prompts(s):
            prev = None
            while prev != s:
                prev = s
                s = _re.sub(r'\s*,\s*,\s*', ', ', s)
            s = _re.sub(r'^\s*,\s*|\s*,\s*$', '', s)
            s = _re.sub(r'[ \t]{2,}', ' ', s)
            return s.strip()

        def remove_rating_tags(s):
            lines = []
            for line in s.splitlines():
                tags = line.split(',')
                kept = []
                for tag in tags:
                    cleaned = tag.strip()
                    if cleaned and not _re.match(r'^rating\s*:', cleaned, _re.IGNORECASE):
                        kept.append(cleaned)
                lines.append(', '.join(kept))
            return '\n'.join(lines)

        def strip_a1111_weights(s):
            prev = None
            while prev != s:
                prev = s
                s = _re.sub(
                    r'\(([^():]+):[+-]?(?:\d+(?:\.\d*)?|\.\d+)\)',
                    lambda m: m.group(1).strip(),
                    s
                )
            return s

        def normalize_people_count_tags(s):
            lines = []
            for line in s.splitlines():
                tags = [tag.strip() for tag in line.split(',') if tag.strip()]
                max_counts = {"girl": 0, "boy": 0}
                kept = []

                for tag in tags:
                    m = _re.fullmatch(r'(\d+)\s*(girls?|boys?)', tag, _re.IGNORECASE)
                    if m:
                        count = int(m.group(1))
                        word = m.group(2).lower()
                        kind = "girl" if word.startswith("girl") else "boy"
                        max_counts[kind] = max(max_counts[kind], count)
                    else:
                        kept.append(tag)

                front = []
                if max_counts["girl"] > 0:
                    n = max_counts["girl"]
                    front.append(f"{n}{'girl' if n == 1 else 'girls'}")
                if max_counts["boy"] > 0:
                    n = max_counts["boy"]
                    front.append(f"{n}{'boy' if n == 1 else 'boys'}")

                lines.append(', '.join(front + kept))
            return '\n'.join(lines)

        result = escape_plain_parentheses(text)

        # 1) N::tag:: 형식: 숫자(정수/소수) + :: + 내용 + ::
        #    내용 안에 :: 가 또 들어가는 케이스는 비탐욕 매칭으로 처리
        def replace_explicit(m):
            weight = m.group(1)
            inner = m.group(2)
            # 내부 재귀 변환 (중첩된 NAI 문법도 처리)
            converted_parts = self.convert(inner, curly_strength, square_strength, decimal_places, max_weight, escape_parentheses)
            inner_converted = converted_parts[0]
            if len(converted_parts) > 1 and converted_parts[1]:
                negative_tags.extend([p.strip() for p in converted_parts[1].split(",") if p.strip()])
            # weight를 float로 정규화 (정수면 정수 표기)
            try:
                w_val = float(weight)
                if w_val <= 0:
                    add_negative_tag(strip_a1111_weights(inner_converted))
                    return ""
                w_val = clamp_weight(w_val)
                w_str = str(int(w_val)) if w_val == int(w_val) else fmt(w_val)
            except ValueError:
                w_str = weight
            return f"({inner_converted}:{w_str})"

        result = _re.sub(r'([+-]?\d+\.?\d*)::([^:]*(?:::[^:]+::[^:]*)*?)::', replace_explicit, result)

        # 2) 중괄호 {} 처리: 가장 안쪽부터 단계적으로 풀어가며 깊이 측정
        #    중첩 {{tag}}는 한 번에 깊이 N으로 잡아서 strength^N 으로 변환
        def collapse_brackets(s, open_ch, close_ch, strength_per_level, is_increase):
            # 가장 안쪽 ( {...} 또는 [...] ) 부터 찾아서 깊이를 카운트
            # 안쪽에 같은 종류 괄호가 없는 매칭부터 처리
            pattern = _re.compile(_re.escape(open_ch) + r'([^' + _re.escape(open_ch) + _re.escape(close_ch) + r']+)' + _re.escape(close_ch))
            # 반복적으로 안쪽부터 처리하면서 외곽 같은 괄호가 또 있으면 깊이 누적
            # 알고리즘: 안쪽 매칭 찾고, 그 매칭 직전/직후가 같은 종류 괄호면 깊이 누적해서 한 번에 변환
            max_iters = 100
            iters = 0
            while iters < max_iters:
                iters += 1
                m = pattern.search(s)
                if not m:
                    break
                start, end = m.start(), m.end()
                inner_text = m.group(1)
                # 외곽으로 같은 괄호 깊이 측정
                depth = 1
                left = start - 1
                right = end
                while left >= 0 and s[left] == open_ch and right < len(s) and s[right] == close_ch:
                    depth += 1
                    left -= 1
                    right += 1
                # 가중치 계산
                if is_increase:
                    weight = strength_per_level ** depth
                else:
                    weight = (1.0 / strength_per_level) ** depth
                weight = clamp_weight(weight)
                replacement = f"({inner_text}:{fmt(weight)})"
                s = s[:left + 1] + replacement + s[right:]
            return s

        result = collapse_brackets(result, '{', '}', curly_strength, True)
        result = collapse_brackets(result, '[', ']', square_strength, False)
        result = result.replace('_', ' ')
        if not escape_parentheses:
            result = result.replace(r"\(", "(").replace(r"\)", ")")
        result = remove_rating_tags(result)
        result = normalize_people_count_tags(result)
        result = cleanup_removed_prompts(result)
        negative = cleanup_removed_prompts(
            remove_rating_tags(
                strip_a1111_weights(
                    ', '.join(negative_tags).replace('_', ' ')
                )
            )
        )

        return (result, negative)


class ConditionalWildcardCombiner:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "action": ("STRING", {"multiline": True, "default": "action1\naction2\naction3"}),
                "char_separator": ("STRING", {"default": ", "}),
                "action_separator": ("STRING", {"default": ", "}),
                "condition_prompt": ("STRING", {"default": ""}),
                "condition_logic": (["any", "all"], {"default": "any"}),
                "match_mode": (["contains", "tag_exact"], {"default": "contains"}),
                "case_sensitive": ("BOOLEAN", {"default": False}),
                "character_source_mode": (["auto", "character_sets", "individual_slots"], {"default": "auto"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 999999}),
            }
            ,
            "optional": FlexibleOptionalInputType(type=any_type, data={
                "character_sets": ("CHARACTER_SET_LISTS",),
                "character_present_sets": ("CHARACTER_SET_LISTS",),
                "character_missing_sets": ("CHARACTER_SET_LISTS",),
            }),
        }

    RETURN_TYPES = ByPassTypeTuple(("STRING", "STRING", "STRING", "STRING", "BOOLEAN", "INT", "INT", "INT"))
    RETURN_NAMES = CharNamesTypeTuple(("combined", "current_action", "current_character", "condition_prompt_used", "condition_matched", "char_index", "action_index", "total_iterations"))
    FUNCTION = "combine"
    CATEGORY = "image/animation"

    def combine(self, action, char_separator=", ", action_separator=", ", condition_prompt="",
                condition_logic="any", match_mode="contains", case_sensitive=False,
                character_source_mode="auto", seed=0, **kwargs):
        def strip_prompt_weight(s):
            s = str(s).strip().replace(r"\(", "(").replace(r"\)", ")")
            prev = None
            while prev != s:
                prev = s
                m = re.fullmatch(r"\((.*)\)", s)
                if m:
                    inner = m.group(1).strip()
                    weight_match = re.fullmatch(r"(.*):[+-]?\d+(?:\.\d+)?", inner)
                    s = (weight_match.group(1) if weight_match else inner).strip()
                    continue
                m = re.fullmatch(r"(.*):[+-]?\d+(?:\.\d+)?", s)
                if m:
                    s = m.group(1).strip()
            return s.replace("_", " ")

        def norm(s):
            s = strip_prompt_weight(s)
            return s if case_sensitive else s.lower()

        def split_prompt_tags(text):
            tags = []
            buf = []
            depth = 0
            escaped = False
            for ch in str(text or ""):
                if escaped:
                    buf.append(ch)
                    escaped = False
                    continue
                if ch == "\\":
                    buf.append(ch)
                    escaped = True
                    continue
                if ch == "(":
                    depth += 1
                elif ch == ")" and depth > 0:
                    depth -= 1
                if ch == "," and depth == 0:
                    tag = "".join(buf).strip()
                    if tag:
                        tags.append(tag)
                    buf = []
                else:
                    buf.append(ch)
            tag = "".join(buf).strip()
            if tag:
                tags.append(tag)
            return tags

        def clean_join(parts, sep):
            return sep.join([p.strip() for p in parts if isinstance(p, str) and p.strip()])

        def parse_prompt_lines(value):
            if value is None:
                return []
            if isinstance(value, (list, tuple)):
                text = "\n".join(str(v) for v in value)
            else:
                text = str(value)
            # Some ComfyUI/string nodes pass escaped newlines as two characters.
            text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
            return [line.strip() for line in text.splitlines() if line.strip()]

        def put_slot_names_first(slot_prompts):
            if len(slot_prompts) <= 1:
                return clean_join(slot_prompts, char_separator)

            name_tags = []
            body_tags = []
            for prompt in slot_prompts:
                tags = [tag.strip() for tag in str(prompt).split(',') if tag.strip()]
                if not tags:
                    continue
                name_tags.append(tags[0])
                body_tags.extend(tags[1:])
            return clean_join(name_tags + body_tags, char_separator)

        def package_slot_lines(package, slot_num):
            if not isinstance(package, dict):
                return []
            slot_lists = package.get("slot_lists", [])
            if not isinstance(slot_lists, (list, tuple)) or slot_num < 1 or slot_num > len(slot_lists):
                return []
            return parse_prompt_lines(slot_lists[slot_num - 1])

        character_sets = kwargs.get("character_sets")
        character_present_sets = kwargs.get("character_present_sets")
        character_missing_sets = kwargs.get("character_missing_sets")
        if character_source_mode == "individual_slots":
            character_sets = None
            character_present_sets = None
            character_missing_sets = None
        package_slot_count = max(
            int(package.get("max_girls", 0) or 0)
            for package in (character_sets, character_present_sets, character_missing_sets)
            if isinstance(package, dict)
        ) if any(isinstance(package, dict) for package in (
            character_sets, character_present_sets, character_missing_sets
        )) else 0

        slot_nums = sorted({
            int(m.group(1))
            for key in kwargs.keys()
            for m in [re.match(r"^char(?:_present|_missing)?_(\d+)$", key)]
            if m
        } | set(range(1, package_slot_count + 1)))

        slot_data = []
        line_count = 0
        for slot_num in slot_nums:
            package_only = character_source_mode == "character_sets"
            char_lines = package_slot_lines(character_sets, slot_num)
            present_lines = package_slot_lines(character_present_sets, slot_num)
            missing_lines = package_slot_lines(character_missing_sets, slot_num)
            if not package_only:
                char_lines = parse_prompt_lines(kwargs.get(f"char_{slot_num}", "")) or char_lines
                present_lines = parse_prompt_lines(kwargs.get(f"char_present_{slot_num}", "")) or present_lines
                missing_lines = parse_prompt_lines(kwargs.get(f"char_missing_{slot_num}", "")) or missing_lines
            slot_line_count = max(len(char_lines), len(present_lines), len(missing_lines))
            line_count = max(line_count, slot_line_count)
            slot_data.append((slot_num, char_lines, present_lines, missing_lines))

        actions = parse_prompt_lines(action)
        if not actions:
            return ("", "", "", "", False, 0, 0, 0) + ("",) * len(slot_nums)

        if not slot_data or line_count <= 0:
            action_idx = seed % len(actions)
            visible_action_parts = []
            for part in split_prompt_tags(actions[action_idx]):
                if not re.fullmatch(r"girl\d+", part.strip(), flags=re.IGNORECASE):
                    visible_action_parts.append(part)
            current_action = clean_join(visible_action_parts, ", ")
            return (
                current_action,
                current_action,
                "",
                "",
                False,
                0,
                action_idx + 1,
                len(actions),
            ) + ("",) * len(slot_nums)

        current_line_idx = (seed // len(actions)) % line_count
        action_idx = seed % len(actions)
        current_action = actions[action_idx]

        # girl1, girl2, ... are control tags selecting the matching char_N
        # slots. Remove these routing-only tags from the emitted action prompt.
        # When no numbered girl tag is present, keep the legacy behavior and
        # use every character slot.
        selected_char_slots = set()
        visible_action_parts = []
        for part in split_prompt_tags(current_action):
            marker_match = re.fullmatch(r"girl(\d+)", part.strip(), flags=re.IGNORECASE)
            if marker_match:
                selected_char_slots.add(int(marker_match.group(1)))
            else:
                visible_action_parts.append(part)
        filter_character_slots = bool(selected_char_slots)
        current_action = clean_join(visible_action_parts, ", ")

        condition_checks = [norm(part) for part in split_prompt_tags(condition_prompt) if part.strip()]
        condition_enabled = bool(condition_checks)
        if not condition_enabled:
            condition_matched = False
        elif match_mode == "tag_exact":
            tags = {norm(part) for part in split_prompt_tags(current_action) if part.strip()}
            matches = [check in tags for check in condition_checks]
            condition_matched = all(matches) if condition_logic == "all" else any(matches)
        else:
            haystack = " ".join(norm(part) for part in split_prompt_tags(current_action))
            matches = [check in haystack for check in condition_checks]
            condition_matched = all(matches) if condition_logic == "all" else any(matches)

        final_slot_chars = []
        condition_used_parts = []
        current_chars_out = [""] * len(slot_nums)
        for slot_idx, (slot_num, char_lines, present_lines, missing_lines) in enumerate(slot_data):
            if filter_character_slots and slot_num not in selected_char_slots:
                continue

            current_character = char_lines[current_line_idx % len(char_lines)] if char_lines else ""
            if not condition_enabled:
                condition_prompt_used = ""
            else:
                present_prompt = present_lines[current_line_idx % len(present_lines)] if present_lines else ""
                missing_prompt = missing_lines[current_line_idx % len(missing_lines)] if missing_lines else ""
                condition_prompt_used = present_prompt.strip() if condition_matched else missing_prompt.strip()

            # 조건용 프롬프트가 있으면 기본 char_N에 덧붙이지 않고 교체한다.
            # 예: head out of frame일 때 일반 캐릭터 프롬프트 대신 눈/얼굴 태그를 뺀 캐릭터 프롬프트 사용.
            slot_character = condition_prompt_used if condition_prompt_used else current_character
            current_chars_out[slot_idx] = slot_character
            if slot_character:
                final_slot_chars.append(slot_character)
            if condition_prompt_used:
                condition_used_parts.append(condition_prompt_used)

        final_character = put_slot_names_first(final_slot_chars)
        condition_prompt_used = clean_join(condition_used_parts, char_separator)
        combined = clean_join([final_character, current_action], action_separator)
        total_iterations = line_count * len(actions)

        return (combined, current_action, final_character, condition_prompt_used,
                condition_matched, current_line_idx + 1, action_idx + 1, total_iterations) + tuple(current_chars_out)


class ConditionalStringRuleEditor:
    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "text": ("STRING", {"default": "", "multiline": True}),
            "match_mode": (["tag_exact", "contains"], {"default": "tag_exact"}),
            "if_logic": (["any", "all"], {"default": "any"}),
            "case_sensitive": ("BOOLEAN", {"default": False, "tooltip": "대소문자 구분. 보통 프롬프트 태그는 끄는 게 편함."}),
            "dedupe_tags": ("BOOLEAN", {"default": True, "tooltip": "중복 태그 제거. 예: 1boy, name, name -> 1boy, name"}),
            "rules_json": ("STRING", {"default": '[{"enabled":true,"if_has":"1boy","unless_has":"pov","add":"name","mode":"after_match"}]'}),
        }
        return {
            "required": inputs,
            "optional": FlexibleOptionalInputType(type=any_type, data={}),
        }

    RETURN_TYPES = ("STRING", "INT", "STRING")
    RETURN_NAMES = ("text", "applied_count", "applied_rules")
    FUNCTION = "apply_rules"
    CATEGORY = "prompt/string"

    def _split_csv(self, value):
        if value is None:
            return []
        text = str(value).replace("\\n", "\n")
        parts = []
        for line in text.splitlines():
            parts.extend(line.split(","))
        return [p.strip() for p in parts if p.strip()]

    def _split_tags(self, text):
        return [p.strip() for p in str(text).split(",") if p.strip()]

    def _norm(self, value, case_sensitive):
        value = self._strip_prompt_weight(value)
        return value if case_sensitive else value.lower()

    def _strip_prompt_weight(self, value):
        value = str(value).strip().replace(r"\(", "(").replace(r"\)", ")")
        prev = None
        while prev != value:
            prev = value
            m = re.fullmatch(r"\((.*)\)", value)
            if m:
                inner = m.group(1).strip()
                weight_match = re.fullmatch(r"(.*):[+-]?\d+(?:\.\d+)?", inner)
                value = (weight_match.group(1) if weight_match else inner).strip()
                continue
            m = re.fullmatch(r"(.*):[+-]?\d+(?:\.\d+)?", value)
            if m:
                value = m.group(1).strip()
        return value

    def _matches(self, text, tags, checks, mode, case_sensitive, logic="any"):
        if not checks:
            return True
        if mode == "tag_exact":
            tag_set = {self._norm(tag, case_sensitive) for tag in tags}
            matcher = lambda check: self._norm(check, case_sensitive) in tag_set
            return all(matcher(check) for check in checks) if logic == "all" else any(matcher(check) for check in checks)
        haystack = text if case_sensitive else text.lower()
        matcher = lambda check: self._norm(check, case_sensitive) in haystack
        return all(matcher(check) for check in checks) if logic == "all" else any(matcher(check) for check in checks)

    def _dedupe(self, tags, case_sensitive):
        seen = set()
        result = []
        for tag in tags:
            key = self._norm(tag, case_sensitive)
            if key in seen:
                continue
            seen.add(key)
            result.append(tag)
        return result

    def _insert_after_first_match(self, tags, include_checks, inserts, case_sensitive):
        if not include_checks:
            return tags + inserts
        checks = {self._norm(check, case_sensitive) for check in include_checks}
        result = []
        inserted = False
        for tag in tags:
            result.append(tag)
            if not inserted and self._norm(tag, case_sensitive) in checks:
                result.extend(inserts)
                inserted = True
        if not inserted:
            result.extend(inserts)
        return result

    def _parse_rules_json(self, rules_json):
        try:
            parsed = json.loads(str(rules_json or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(parsed, list):
            return []

        valid_modes = {"after_match", "prepend", "append", "replace_match"}
        rules = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            mode = str(item.get("mode", "after_match"))
            rules.append({
                "enabled": bool(item.get("enabled", True)),
                "include": str(item.get("if_has", item.get("include", "")) or ""),
                "exclude": str(item.get("unless_has", item.get("exclude", "")) or ""),
                "insert": str(item.get("add", item.get("insert", "")) or ""),
                "mode": mode if mode in valid_modes else "after_match",
            })
        return rules

    def apply_rules(self, text, match_mode="tag_exact", if_logic="any", case_sensitive=False, dedupe_tags=True,
                    rules_json="[]", **kwargs):
        result_text = str(text or "")
        applied = []
        rules = self._parse_rules_json(rules_json)
        for idx, rule in enumerate(rules, start=1):
            connected_add = kwargs.get(f"rule_{idx} add")
            if connected_add is not None:
                rule["insert"] = str(connected_add)
            rule["name"] = f"rule_{idx}"

        for idx, rule in enumerate(rules, start=1):
            if not isinstance(rule, dict) or not rule.get("enabled", True):
                continue
            include = self._split_csv(rule.get("include", ""))
            exclude = self._split_csv(rule.get("exclude", ""))
            insert = self._split_csv(rule.get("insert", ""))
            if not insert:
                continue

            tags = self._split_tags(result_text)
            if not self._matches(result_text, tags, include, match_mode, case_sensitive, if_logic):
                continue
            if exclude and self._matches(result_text, tags, exclude, match_mode, case_sensitive):
                continue

            mode = str(rule.get("mode", "after_match"))
            if mode == "prepend":
                tags = insert + tags
            elif mode == "append":
                tags = tags + insert
            elif mode == "replace_match":
                include_keys = {self._norm(v, case_sensitive) for v in include}
                tags = [
                    tag for tag in tags
                    if self._norm(tag, case_sensitive) not in include_keys
                ] + insert
            else:
                tags = self._insert_after_first_match(tags, include, insert, case_sensitive)

            if dedupe_tags:
                tags = self._dedupe(tags, case_sensitive)
            result_text = ", ".join(tags)
            applied.append(str(rule.get("name") or f"rule_{idx}"))

        return (result_text, len(applied), ", ".join(applied))


class H3ContinuumPriorFinalPrompt:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prior_prompt": ("STRING", {"forceInput": True}),
                "final_prompt": ("STRING", {"forceInput": True}),
                "chunks": ("INT", {"default": 2, "min": 1, "max": 64, "step": 1}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("sequence_prompt",)
    FUNCTION = "build"
    CATEGORY = "wildcard_image_iterator/prompt"

    def build(self, prior_prompt, final_prompt, chunks=2):
        chunk_count = int(chunks)
        if chunk_count < 1:
            raise ValueError("chunks must be at least 1")

        prior = str(prior_prompt or "").strip()
        final = str(final_prompt or "").strip()
        if not prior:
            raise ValueError("prior_prompt is empty")
        if chunk_count <= 1:
            return (prior,)
        if not final:
            raise ValueError("final_prompt is empty")

        prompts = ([prior] * (chunk_count - 1)) + [final]
        return ("\n---\n".join(prompts),)


NODE_CLASS_MAPPINGS = {
    "WildcardImageIterator": WildcardImageIterator,
    "WildcardFileLoader": WildcardFileLoader,
    "WildcardTextProcessor": WildcardTextProcessor,
    "WildcardMultiFileLoader": WildcardMultiFileLoader,
    "WildcardBatchController": WildcardBatchController,
    "LoadImageBatchFromDirWithFilename": LoadImageBatchFromDirWithFilename,
    "WildcardCombiner": WildcardCombiner,
    "StringToLatent": StringToLatent,
    "ImageSaver": ImageSaver,
    "SaveImageExtendedSeedCounterWildcard": SaveImageExtendedSeedCounterWildcard,
    "VideoFromFolderLoader": VideoFromFolderLoader,
    "VideoFromFolderLoaderSimple": VideoFromFolderLoaderSimple,
    "VideoFromFolderLoaderChunk": VideoFromFolderLoaderChunk,
    "ConcatImageChunks": ConcatImageChunks,
    "VideoSaver": VideoSaver,
    "VideoConcat": VideoConcat,
    "VideoConcatBatch": VideoConcatBatch,
    "VideoLoopPlanner": VideoLoopPlanner,
    "VideoLoopSourceFilename": VideoLoopSourceFilename,
    "VideoLoopStartFrame": VideoLoopStartFrame,
    "VideoLoopConcatFinal": VideoLoopConcatFinal,
    "VideoCompareSplit": VideoCompareSplit,
    "ImageMaxMinDimension": ImageMaxMinDimension,
    "LoopStableImageAutosize": LoopStableImageAutosize,
    "WildcardCyclePicker": WildcardCyclePicker,
    "NaiToA1111Weight": NaiToA1111Weight,
    "ConditionalWildcardCombiner": ConditionalWildcardCombiner,
    "ConditionalStringRuleEditor": ConditionalStringRuleEditor,
    "H3ContinuumPriorFinalPrompt": H3ContinuumPriorFinalPrompt,
    "MemoryCleanupBridge": MemoryCleanupBridge,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WildcardTextProcessor": "Wildcard Text Processor",
    "LoopStableImageAutosize": "Loop Stable Image Autosize",
    "WildcardImageIterator": "Wildcard Image Iterator 🔄",
    "WildcardFileLoader": "Wildcard File Loader 📁",
    "WildcardMultiFileLoader": "Wildcard Multi File Loader 📚",
    "WildcardBatchController": "Wildcard Batch Controller ⚙️",
    "LoadImageBatchFromDirWithFilename": "Load Image Batch From Dir + Filename 📂",
    "WildcardCombiner": "Wildcard Combiner 🔗",
    "StringToLatent": "String To Latent 📐",
    "ImageSaver": "Image Saver 💾",
    "SaveImageExtendedSeedCounterWildcard": "Save Image Extended (Seed Counter) 💾",
    "VideoFromFolderLoader": "Video From Folder Loader 🎬",
    "VideoFromFolderLoaderSimple": "Video From Folder Loader (Simple) 🎬",
    "VideoFromFolderLoaderChunk": "Video From Folder Loader (Chunk) 🎬🧩",
    "ConcatImageChunks": "Concat Image Chunks (Low Memory) 🔗🖼️",
    "VideoSaver": "Video Saver 💾🎬",
    "VideoConcat": "Video Concat 🔗🎬",
    "VideoConcatBatch": "Video Concat Batch 🔗🔗🎬",
    "VideoLoopPlanner": "Video Loop Planner 🔁🎬",
    "VideoLoopSourceFilename": "Video Loop Source Filename 🔁🏷️",
    "VideoLoopStartFrame": "Video Loop Start Frame 🔁🖼️",
    "VideoLoopConcatFinal": "Video Loop Concat Final 🔁🔗🎬",
    "VideoCompareSplit": "Video Compare (Split-Screen) 🎬⚖️",
    "ImageMaxMinDimension": "Image Max/Min Dimension 📐",
    "WildcardCyclePicker": "Wildcard Cycle Picker 🔁🎴",
    "NaiToA1111Weight": "NAI → A1111 Weight Convert 🔄",
    "ConditionalWildcardCombiner": "Conditional Wildcard Combiner",
    "ConditionalStringRuleEditor": "Conditional String Rule Editor",
    "H3ContinuumPriorFinalPrompt": "H3 Continuum Prior + Final Prompt",
    "MemoryCleanupBridge": "Memory Cleanup Bridge 🧹",
}
