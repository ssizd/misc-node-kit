# ComfyUI Wildcard Image Iterator

이미지 투 비디오 워크플로우에서 각 이미지마다 와일드카드 프롬프트 목록을 모두 순회하는 ComfyUI 커스텀 노드입니다.

## 설치 방법

1. zip 파일을 다운로드하고 압축을 해제합니다.

2. `wildcard_image_iterator` 폴더 전체를 ComfyUI의 `custom_nodes` 폴더에 복사합니다:
```
ComfyUI/
└── custom_nodes/
    └── wildcard_image_iterator/
        ├── __init__.py
        ├── wildcard_image_iterator.py
        ├── README.md
        └── wildcards/
            ├── styles.txt
            ├── camera_movements.txt
            └── moods.txt
```

3. ComfyUI를 재시작하면 노드가 나타납니다.

## 노드 설명

### 1. Wildcard Image Iterator 🔄
메인 노드로, 폴더 내의 각 이미지에 대해 와일드카드 목록의 모든 프롬프트를 순회합니다.

**입력:**
- `image_folder`: 이미지가 있는 폴더 경로 (ComfyUI의 input 폴더 기준 상대 경로 또는 절대 경로)
- `wildcard_list`: 프롬프트 목록 (줄바꿈으로 구분)
- `separator`: 구분자 (기본값: `\n`)
- `reset`: 인덱스 초기화 여부
- `seed`: (선택) 시드값

**출력:**
- `current_image`: 현재 처리 중인 이미지
- `current_prompt`: 현재 프롬프트
- `image_filename`: 현재 이미지 파일명
- `image_index`: 현재 이미지 인덱스
- `wildcard_index`: 현재 와일드카드 인덱스
- `total_iteration`: 총 반복 횟수
- `is_complete`: 완료 여부

### 2. Wildcard File Loader 📁
`wildcards` 폴더(서브폴더 포함)에서 와일드카드 목록을 불러옵니다.

**입력:**
- `wildcard_file`: 와일드카드 파일 선택 (드롭다운 메뉴, 서브폴더 파일도 표시됨)
- `mode`: 증가 방식
  - `sequential`: 순차적으로 (1, 2, 3...)
  - `random`: 랜덤으로 섞음
- `seed`: 랜덤 시드 (mode가 random일 때만 사용)

**출력:**
- `wildcard_list`: 로드된 와일드카드 목록 (줄바꿈으로 구분)
- `wildcard_count`: 프롬프트 개수

### 3. Wildcard Batch Controller ⚙️
배치 처리를 제어합니다.

**입력:**
- `is_complete`: 완료 여부
- `max_iterations`: 최대 반복 횟수

**출력:**
- `continue_batch`: 계속 진행 여부

## 사용 예제

### 기본 워크플로우 구성

```
[Wildcard Image Iterator] → [I2V Model] → [Save Video]
         ↑
[Wildcard File Loader]
```

### 상세한 연결 방법

1. **이미지 준비**
   - ComfyUI의 `input` 폴더에 이미지들을 넣습니다
   - 예: `ComfyUI/input/my_images/` 폴더에 image1.png, image2.png, image3.png

2. **와일드카드 설정**
   ```
   [Wildcard File Loader]
   wildcard_file: "DB01-Girl.txt" (또는 "characters/heroes.txt")
   mode: "sequential"
   ↓
   [Wildcard Image Iterator]
   image_folder: "my_images"
   wildcard_list: (Wildcard File Loader의 wildcard_list 출력 연결)
   ```

3. **Image-to-Video 모델 연결**
   ```
   [Wildcard Image Iterator]
   current_image → [I2V Model]의 image 입력
   current_prompt → [I2V Model]의 prompt 입력
   image_filename → [Save Video]의 filename_prefix (선택)
   ```

4. **프롬프트 미리보기 (선택)**
   ```
   [Wildcard Image Iterator]
   current_prompt → [Show Text] 노드
   ```
   이렇게 하면 현재 어떤 프롬프트가 사용되는지 볼 수 있습니다.

5. **비디오 저장**
   ```
   [I2V Model] → [Save Video]
   filename_prefix: "{image_filename}_{wildcard_index}"
   ```

### 와일드카드 파일 만들기

`wildcards` 폴더(또는 서브폴더)에 `.txt` 파일로 프롬프트를 저장합니다.

**폴더 구조 예시:**
```
wildcard_image_iterator/
└── wildcards/
    ├── styles.txt
    ├── camera_movements.txt
    ├── moods.txt
    ├── DB01-Girl.txt
    └── characters/
        └── heroes.txt
```

**예제 - `DB01-Girl.txt` (캐릭터 프롬프트):**
```
Ari \(dynamite blue\), 1girl, long hair, brown hair, medium breasts, green eyes
lilly \(dynamite blue\), 1girl, breasts, short hair, blue hair, purple eyes
RU \(dynamite blue\), 1girl, short hair, blue eyes, blue hair, white hair
```

**예제 - `styles.txt` (스타일 프롬프트):**
```
cinematic lighting, dramatic atmosphere
soft pastel colors, dreamy mood
high contrast, bold shadows
```

**서브폴더 사용:**
- `characters/heroes.txt` → 드롭다운에 "characters/heroes.txt"로 표시됨
- 서브폴더를 사용하여 와일드카드를 카테고리별로 정리 가능

새 와일드카드 파일을 추가하면 ComfyUI를 재시작한 후 드롭다운 메뉴에 자동으로 나타납니다.

### 고급 워크플로우 (루프)

ComfyUI Manager의 Loop 노드와 함께 사용:

```
[Start Loop]
    ↓
[Wildcard Image Iterator]
    ↓
[I2V Model]
    ↓
[Save Video]
    ↓
[Wildcard Batch Controller] → is_complete 체크
    ↓
[End Loop] (continue_batch가 True면 다시 반복)
```

## 작동 원리

1. 첫 번째 이미지 + 첫 번째 프롬프트로 비디오 생성
2. 첫 번째 이미지 + 두 번째 프롬프트로 비디오 생성
3. ...
4. 첫 번째 이미지 + 마지막 프롬프트로 비디오 생성
5. 두 번째 이미지 + 첫 번째 프롬프트로 비디오 생성
6. 반복...

**예시:**
- 이미지 3개, 프롬프트 5개 → 총 15개의 비디오 생성
- 순서: (이미지1, 프롬프트1), (이미지1, 프롬프트2), ..., (이미지3, 프롬프트5)

## 팁

1. **이미지 폴더 설정**
   - 상대 경로: `my_images` (ComfyUI/input/my_images/)
   - 절대 경로: `C:/Users/Username/Pictures/my_images`
   - 지원 형식: jpg, jpeg, png, bmp, webp, tiff

2. **와일드카드 파일 관리**
   - `wildcards` 폴더 및 서브폴더에 `.txt` 파일로 저장
   - 서브폴더 사용 가능: `wildcards/characters/heroes.txt`
   - 파일명은 자유롭게 (예: `my_prompts.txt`)
   - UTF-8 인코딩으로 저장
   - 새 파일 추가 후 ComfyUI 재시작

3. **프롬프트 작성**
   - 한 줄에 하나의 프롬프트 (자동으로 줄바꿈으로 구분)
   - 빈 줄은 자동으로 무시됨
   - 쉼표로 여러 요소 조합 가능

4. **프롬프트 확인**
   - `current_prompt` 출력을 Show Text 노드에 연결하면 실시간으로 볼 수 있음
   - 콘솔에서도 현재 프롬프트가 출력됨

5. **배치 처리**
   - `max_iterations`를 충분히 크게 설정 (이미지 수 × 프롬프트 수)
   - 메모리가 부족하면 이미지를 더 작은 폴더로 나누기

6. **디버깅**
   - 콘솔에서 현재 진행 상황 확인 가능
   - `image_index`, `wildcard_index` 출력을 모니터링
   - `image_filename`으로 현재 처리 중인 파일 확인

## 문제 해결

**Q: 노드가 나타나지 않아요**
- ComfyUI를 완전히 재시작했는지 확인
- `wildcard_image_iterator` 폴더가 `custom_nodes` 안에 있는지 확인
- 콘솔에서 에러 메시지 확인

**Q: 이미지 폴더를 찾을 수 없다고 나와요**
- 상대 경로는 `ComfyUI/input/` 폴더 기준입니다
- 절대 경로를 사용해보세요 (예: `C:/Users/Username/Pictures/images`)
- 폴더 경로에 한글이나 특수문자가 있으면 문제가 될 수 있습니다

**Q: 이미지 폴더에 이미지가 없다고 나와요**
- 지원하는 형식인지 확인: jpg, jpeg, png, bmp, webp, tiff
- 파일 확장자가 소문자인지 확인

**Q: 와일드카드 파일이 드롭다운에 안 보여요**
- 파일이 `wildcards` 폴더 안에 있는지 확인
- 파일 확장자가 `.txt`인지 확인
- ComfyUI를 재시작했는지 확인

**Q: 반복이 멈추지 않아요**
- `max_iterations` 값 확인
- Batch Controller 노드 사용

## 라이선스

MIT License - 자유롭게 사용, 수정, 배포 가능합니다.
