import json
from jinja2 import Template
import os
from argparse import ArgumentParser
base = os.path.dirname(os.path.abspath(__file__))

def main():
   parser = ArgumentParser(description='hoge')
   parser.add_argument('file', type=str, help="json file")
   parser.add_argument('-o', '--output_dir', type=str, help="output file dir", default=os.path.abspath(os.path.join(base, './output')))
   args = parser.parse_args()

   save_dir = os.path.abspath(args.output_dir)
   if not os.path.exists(save_dir):
      os.makedirs(save_dir)
   with open(os.path.abspath(args.file), 'r', encoding='utf-8') as fin:
      source = json.load(fin)


   with open(os.path.abspath(os.path.join(base, './temp/ros2_graph_template.html')), 'r', encoding='utf-8') as fin:
      temp = Template(source=fin.read())
   output_str = temp.render(elements_data=source)
   with open(os.path.join(save_dir, "index.html"), 'w', encoding='utf-8') as fout:
      fout.write(output_str)

if __name__ == '__main__':
    print("generate html")
    main()