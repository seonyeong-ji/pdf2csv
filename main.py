import streamlit as st
import pandas as pd
import pdfplumber
import csv
from collections import defaultdict

@st.cache_data
def get_coordinate(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        pages = pdf.pages

        char_list = []
        for i, page in enumerate(pages):
            id = 0
            temps = []      # 중복요소 제거용 리스트
            for char in page.chars:
                page = i+1
                id += 1
                text_id = "%s_%s" % (page, id)

                x0 = char["x0"]
                y0 = char["y0"]
                x1 = char["x1"]
                y1 = char["y1"]
                width = char["width"]
                height = char["height"]
                text = char["text"]

                fontname = char["fontname"]
                size = char["size"]

                # 모든 조건이 같은 요소(char)를 제거하기 위해 x0부터 text까지를 string으로 붙여서 중복검사를 했습니다.
                temp = "%s_%s_%s_%s_%s_%s_%s" % (x0,y0,x1,y1,width,height,text)
                if temp not in temps:
                    char_list.append({"x0":x0, "y0":y0, "x1":x1, "y1":y1, "width":width, "height":height, "text":text, "page":page, "text_id":text_id})
                    temps.append("%s_%s_%s_%s_%s_%s_%s" % (x0,y0,x1,y1,width,height,text))

    # page, y0, x0 기준으로 정렬 (y0는 내림차순 정렬)
    char_list_sorted = sorted(char_list, key=lambda item: (item['page'], -item['y0'], item['x0']))

    return char_list_sorted

@st.cache_data
def merge_grouped_boxes(grouped_boxes):
    new_bounding_boxes = []
    for (y0, page, _), boxes in grouped_boxes.items():
        min_x0 = min(box['x0'] for box in boxes)
        max_x1 = max(box['x1'] for box in boxes)
        max_y1 = max(box['y1'] for box in boxes)
        merged_text = ''.join(box['text'] for box in boxes)
        new_box = {
            'x0': min_x0,
            'y0': y0,
            'x1': max_x1,
            'y1': max_y1,
            'width': max_x1 - min_x0,
            'height': max_y1 - y0,
            'text': merged_text,
            'page': page
        }
        new_bounding_boxes.append(new_box)
    return new_bounding_boxes

@st.cache_data
def merge_bounding_boxes(bounding_boxes):
    # 1. 그룹화
    grouped_boxes = defaultdict(list)
    for box in bounding_boxes:
        grouped_boxes[(box['y0'], box['page'])].append(box)

    # 2. 새 좌표 계산 및 텍스트 병합
    new_bounding_boxes = merge_grouped_boxes(grouped_boxes)

    return new_bounding_boxes

@st.cache_data
def merge_bounding_boxes_with_y_threshold(bounding_boxes):
   pre_grouped = defaultdict(list)
   for box in bounding_boxes:
      pre_grouped[(box['y0'], box['page'])].append(box)

   grouped_boxes = group_boxes_with_y_threshold(pre_grouped)
   merged_boxes = merge_grouped_boxes(grouped_boxes)

   merged_boxes.sort(key=lambda box: (box['page'], -box['y0']))

   return merged_boxes

@st.cache_data
def group_boxes_with_y_threshold(pre_grouped):
   final_grouped = defaultdict(list)
   for (y0, page), group in pre_grouped.items():
      sorted_group = sorted(group, key=lambda b: b['x0'])
      if len(sorted_group) > 1:
         x_diffs = [sorted_group[i + 1]['x0'] - sorted_group[i]['x1'] for i in range(len(sorted_group) - 1)]
         avg_x_diff = sum(x_diffs) / len(x_diffs) if x_diffs else 0
         threshold = max(avg_x_diff * 1.5, 10)  # 최소 threshold를 10으로 설정

         current_group = [sorted_group[0]]
         for i in range(1, len(sorted_group)):
            if sorted_group[i]['x0'] - sorted_group[i - 1]['x1'] > threshold:
               final_grouped[(y0, page, id(current_group))].extend(current_group)
               current_group = []
            current_group.append(sorted_group[i])

         if current_group:
            final_grouped[(y0, page, id(current_group))].extend(current_group)
      else:
         final_grouped[(y0, page, id(sorted_group))].extend(sorted_group)

   return final_grouped


@st.cache_data
def process_bounding_boxes(bounding_boxes):
    # 1. 단일 문자 박스와 긴 텍스트 박스 분리
    single_char_boxes = [box for box in bounding_boxes if len(box['text']) == 1]
    long_text_boxes = [box for box in bounding_boxes if len(box['text']) > 1]

    # 2. 단일 문자 박스 병합 함수
    def merge_single_char_boxes(boxes):
        grouped_boxes = defaultdict(list)
        for box in boxes:
            grouped_boxes[(box['x0'], box['page'])].append(box)

        merged_boxes = []
        for (x0, page), group in grouped_boxes.items():
            if len(group) > 1:
                min_y0 = min(box['y0'] for box in group)
                max_y1 = max(box['y1'] for box in group)
                max_x1 = max(box['x1'] for box in group)
                merged_text = ''.join(box['text'] for box in group)
                merged_box = {
                    'page': page,
                    'text': merged_text,
                    'x0': x0,
                    'y0': min_y0,
                    'x1': max_x1,
                    'y1': max_y1,
                    'width': max_x1 - x0,
                    'height': max_y1 - min_y0
                }
                merged_boxes.append(merged_box)
            else:
                merged_boxes.extend(group)
        return merged_boxes

    # 3. 단일 문자 박스 병합 실행
    merged_single_char_boxes = merge_single_char_boxes(single_char_boxes)

    # 4. 병합된 단일 문자 박스와 긴 텍스트 박스 통합
    final_boxes = merged_single_char_boxes + long_text_boxes

    # 5. 결과 정렬 (선택사항: 페이지 및 y0 좌표 기준)
    final_boxes.sort(key=lambda box: (box['page'], -box['y0'], box['x0']))

    return final_boxes

@st.cache_data
def save_csv(merge_bboxs, file_path):
    with open(file_path, 'w', newline='', encoding='utf-8-sig') as csv_file:
        fieldnames = ['page', "text", 'x0', 'y0', 'width', 'height']
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)

        writer.writeheader()
        for bbox in merge_bboxs:
            x0 = bbox["x0"]
            y0 = bbox["y0"]
            width = bbox["width"]
            height = bbox["height"]
            text = bbox["text"]
            page = bbox["page"]
            writer.writerow({"page":page, "text":text, "x0":x0, "y0":y0, "width":width, "height":height })


if __name__ == '__main__':
   st.set_page_config(page_title="BoinIT TextPDF2CSV")

   st.title("TEXT PDF to CSV")
   st.subheader("TEXT PDF 파일의 좌표와 텍스트를 CSV로 출력합니다.")
   st.text("배포일 2024-08-05\n"
           "연락처 미래기획팀 지선영 대리(syji@boinit.com)\n
           python 사용이 익숙하신 분은 https://github.com/seonyeong-ji/pdf2csv 에서 코드를 직접 다운받아 커스텀하여 사용하실 수 있습니다.")


   pdf_file = st.file_uploader('PDF 파일 업로드', type=['PDF', 'pdf'])

   if pdf_file:
       with st.spinner('잠시만 기다려주세요.'):
           char_list_sorted = get_coordinate(pdf_file)
           merge_bboxs = merge_bounding_boxes_with_y_threshold(char_list_sorted)
           merge_bboxs = process_bounding_boxes(merge_bboxs)


           pd_data = pd.DataFrame(merge_bboxs)
           pd_data = pd_data[['page', 'text', 'x0', 'y0', 'width', 'height']]
           output = pd_data.to_csv(index_label=['No.']).encode('utf-8-sig')

       st.success("완료!")

       st.download_button(
          "csv 파일 다운로드",
          output,
          "%s.csv" % pdf_file.name.split(".")[0],
          "./",
          key='download-csv'
       )

       st.markdown("다음 파일을 변환하려면 'Browse files' 아이콘을 눌러 pdf 파일을 재업로드 해주세요.")
