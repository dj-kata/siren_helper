import cv2
from onnxocr.onnx_paddleocr import ONNXPaddleOcr
import sys

# 1. OCRエンジンの初期化
ocr = ONNXPaddleOcr(use_gpu=False, lang="japan")

for f in sys.argv[1:]:
    # 2. OpenCVで画像を読み込む（ここが修正ポイント）
    img = cv2.imread(f)

    # 3. 読み込んだ画像データを渡す
    result = ocr.ocr(img, cls=False)

    # 結果の表示
    print(result)

    for data in result:
        # 認識結果が空でないか確認
        if data:
            for box, (text, score) in data:
                print(f"text: {text}, score: {score}")
