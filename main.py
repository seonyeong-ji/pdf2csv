import streamlit as st
import pandas as pd
import pdfplumber
from collections import defaultdict

@st.cache_data
def proc_pdf(pdf_path):
    # pdf 파일에서 텍스트의 음절 단위 좌표를 받아오는 함수
    with pdfplumber.open(pdf_path) as pdf:
        pages = pdf.pages

        char_list = []
        for i, page in enumerate(pages):
            id = 0
            temps = []      # 중복요소 제거용 리스트
            for char in page.chars:
                page = i+1
                id += 1

                # page와 char 등장 순서대로 id를 매김. 추후 사용하지 않으나 예비용으로 생성
                char_id = "%s_%s" % (page, id)

                x0 = char["x0"]
                y0 = char["y0"]
                x1 = char["x1"]
                y1 = char["y1"]
                width = char["width"]
                height = char["height"]
                text = char["text"]

                # fontname, size 모두 사용하지 않았음
                fontname = char["fontname"]
                size = char["size"]

                # 중복 등장하는 음절을 제거하기 위해 x0부터 text까지 string으로 붙여서 중복검사
                temp = "%s_%s_%s_%s_%s_%s_%s" % (x0,y0,x1,y1,width,height,text)
                if temp not in temps:
                    # 리스트-딕셔너리가 중첩된 형태로 리턴
                    temps.append("%s_%s_%s_%s_%s_%s_%s" % (x0,y0,x1,y1,width,height,text))
                    char_list.append({"x0":x0, "y0":y0, "x1":x1, "y1":y1, "width":width, "height":height, "text":text, "page":page, "char_id":char_id})

    # page, y0, x0 순서대로 정렬 (y0는 내림차순 정렬)
    char_list_sorted = sorted(char_list, key=lambda item: (item['page'], -item['y0'], item['x0']))

    return char_list_sorted


@st.cache_data
def merge_bboxes_with_y(bounding_boxes):
    '''
    음절 단위로 받은 좌표값을 라인 단위로 병합 (1차 병합)
    :param bounding_boxes:
    :return:
    '''
    pre_grouped = defaultdict(list)

    # 같은 y0을 가진 음절끼리 묶음
    for box in bounding_boxes:
        pre_grouped[(box['y0'], box['page'])].append(box)

    # 같은 y0을 가진 음절 병합
    grouped_boxes = merge_bboxes_with_y_threshold(pre_grouped)

    # 병합한 bbox 좌표 후처리
    merged_boxes = proc_coordicate_y0(grouped_boxes)

    # 후처리한 bbox 좌표를 페이지 기준으로 오름차순, y0 기준으로 내림차순 정렬
    merged_boxes.sort(key=lambda box: (box['page'], -box['y0']))

    return merged_boxes


@st.cache_data
def merge_bboxes_with_y_threshold(pre_grouped):
    '''
    y0이 같은 음절을 병합
    threshold를 10으로 설정해서 y0가 같더라도 글자와 글자 사이가 많이 떨어진 글자는 서로 다른 단위로 인식함.
    예 : 사과        바나나 -> '사과', '바나나'로 인식함
    :param pre_grouped:
    :return:
    '''

    final_grouped = defaultdict(list)
    for (y0, page), group in pre_grouped.items():
        # x0을 기준으로 오름차순 정렬. 사람이 읽는 순서대로 정렬하기 위함
        sorted_group = sorted(group, key=lambda b: b['x0'])

        # y0 값이 같은 음절이 2개 이상 있는 경우에만 병합
        # <1은 추후 세로정렬로 처리함
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
def proc_coordicate_y0(grouped_boxes):
    '''
    y0 기준으로 병합한 box의 새로운 좌표값 계산
    :param grouped_boxes:
    :return:
    '''
    merged_boxes = []
    for (y0, page, _), boxes in grouped_boxes.items():
        min_x0 = min(box['x0'] for box in boxes)
        max_x1 = max(box['x1'] for box in boxes)
        max_y1 = max(box['y1'] for box in boxes)
        merged_text = ''.join(box['text'] for box in boxes)
        merged_box = {
            'x0': min_x0,
            'y0': y0,
            'x1': max_x1,
            'y1': max_y1,
            'width': max_x1 - min_x0,
            'height': max_y1 - y0,
            'text': merged_text,
            'page': page
        }
        merged_boxes.append(merged_box)
    return merged_boxes


@st.cache_data
def merge_bboxes_with_x(bounding_boxes):
    '''
    세로정렬된 텍스트 병합
    :param bounding_boxes: 
    :return: 
    '''
    # 어절이 1개인 bbox(single_char_boxes)와 2개 이상인 bbox(multi_char_boxes) 분리
    single_char_boxes = [box for box in bounding_boxes if len(box['text']) == 1]
    multi_char_boxes = [box for box in bounding_boxes if len(box['text']) > 1]

    # x0 기준으로 bbox 병합
    merged_single_char_boxes = proc_coordicate_x0(single_char_boxes)

    # boxes 리스트 통합
    final_boxes = merged_single_char_boxes + multi_char_boxes

    # 통합한 boxes 리스트 재정렬. 페이지 기준 오름차순, y0 기준 내림차순, x0 기준 오름차순
    # 최대한 사람이 읽는 순서대로 정렬
    final_boxes.sort(key=lambda box: (box['page'], -box['y0'], box['x0']))

    return final_boxes


@st.cache_data
def proc_coordicate_x0(boxes):
    '''
    x0 기준으로 병합한 box의 새로운 좌표값 계산
    :param boxes: 
    :return: 
    '''
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


if __name__ == '__main__':
   st.set_page_config(page_title="BoinIT TextPDF2CSV")

   st.title("TEXT PDF to CSV")
   st.subheader("TEXT PDF 파일에서 텍스트만 CSV 파일로 출력해줍니다.")

   st.text("배포일 2024-08-05\n"
           "연락처 미래기획팀 지선영 대리(syji@boinit.com)\n"
           "python 사용이 익숙하신 분은 저에게 연락주세요. 커스텀하실 수 있도록 원본 코드 제공 가능합니다.")
   st.divider()
	
   if st.button("Reset"):
       st.session_state.value = "Reset"
       st.rerun()

   pdf_file = st.file_uploader('PDF 파일 업로드', type=['PDF', 'pdf'])

   if pdf_file:
       with st.spinner('잠시만 기다려주세요.'):
           
           # get char coordinate
           char_list_sorted = proc_pdf(pdf_file)
           
           # merge y0
           merge_bboxs = merge_bboxes_with_y(char_list_sorted)
           
           # merge x0
           merge_bboxs = merge_bboxes_with_x(merge_bboxs)
           
           # export csv
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

       st.markdown("다음 파일을 변환하려면 'Reset', 'Browse files' 버튼을 순서대로 눌러 pdf 파일을 재업로드 해주세요.")
