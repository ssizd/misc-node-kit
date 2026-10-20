# 빠른 시작 가이드

## 1단계: 설치
1. `wildcard_image_iterator.zip` 다운로드 & 압축 해제
2. `wildcard_image_iterator` 폴더를 `ComfyUI/custom_nodes/`에 복사
3. ComfyUI 재시작

## 2단계: 이미지 준비
ComfyUI의 `input` 폴더에 이미지를 준비합니다:
```
ComfyUI/
└── input/
    └── my_images/
        ├── image1.png
        ├── image2.png
        └── image3.png
```

## 3단계: 와일드카드 파일 준비
`wildcards` 폴더에 이미 3개의 예제 파일이 포함되어 있습니다:
- `styles.txt` - 조명 및 스타일
- `camera_movements.txt` - 카메라 움직임
- `moods.txt` - 분위기/무드

새 파일을 추가하려면:
1. `wildcards` 폴더에 `.txt` 파일 생성
2. 한 줄에 하나의 프롬프트 작성
3. ComfyUI 재시작

## 4단계: 워크플로우 구성

### 기본 구성:
```
[Wildcard File Loader] → [Wildcard Image Iterator] → [I2V Model] → [Save Video]
```

### 노드 연결:
1. **Wildcard File Loader**: 
   - `wildcard_file`: 원하는 파일 선택 (예: styles.txt)
   
2. **Wildcard Image Iterator**:
   - `image_folder`: "my_images" (또는 절대 경로)
   - `wildcard_list`: Wildcard File Loader의 출력 연결
   
3. **I2V Model**:
   - `image`: Wildcard Image Iterator의 `current_image` 연결
   - `prompt`: Wildcard Image Iterator의 `current_prompt` 연결
   
4. **Save Video**: 
   - I2V Model 출력 연결
   - `filename_prefix`: "{image_filename}_{wildcard_index}" 같은 형식 사용 가능

## 5단계: 실행
- Queue Prompt 버튼 클릭
- 각 이미지에 대해 모든 프롬프트가 자동으로 실행됩니다
- 콘솔에서 진행 상황을 확인하세요

## 결과
- **이미지 3개 + 프롬프트 5개 = 15개 비디오**
- 순서: (이미지1, 프롬프트1) → (이미지1, 프롬프트2) → ... → (이미지3, 프롬프트5)

## 폴더 경로 예시

### 상대 경로 (추천):
```
image_folder: "my_images"
→ ComfyUI/input/my_images/ 폴더 사용
```

### 절대 경로:
```
Windows: "C:/Users/Username/Pictures/images"
Linux/Mac: "/home/username/images"
```

## 팁
- 프롬프트가 많으면 시간이 오래 걸립니다
- 먼저 1-2개 이미지와 2-3개 프롬프트로 테스트해보세요
- 콘솔에서 진행 상황을 확인하세요
- `image_filename` 출력을 활용해 파일명 기반 저장 가능
