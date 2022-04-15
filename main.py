import os
import yaml
import csv

data = []
textFields = ['title','created-at','last-update','library-classification','language']
listFields = ['domain']
structuredListFields = {
  'style': ['ufo', 'ontouml', 'industry'],
  'types': ['core', 'domain', 'application'],
  'context': ['classroom', 'research', 'industry'],
  'purpose': ['conceptual clarification', 'data publication', 'decision support system', 'example', 'information retrieval', 'interoperability', 'language engineering', 'learning', 'ontological analysis', 'software engineering']
}

header = ['directory', *textFields, *listFields]

for field in structuredListFields:
  for value in structuredListFields[field]:
    header.append(field+"-"+value)

for path in os.listdir():
  metadataPath = path+"/metadata.yaml"
  
  if(not os.path.isdir(path) or path==".git" or not os.path.isfile(metadataPath)):
    continue

  print(metadataPath)

  with open(metadataPath) as file:
    metadata = yaml.load(file, Loader=yaml.FullLoader)
    
    row = [path]
    data.append(row)

    for field in textFields:
      value = ''
      
      if field in metadata:
        value = metadata[field]

      row.append(value)
    
    for field in listFields:
      value = ''
      
      if(type(metadata[field]) == list):
        value = ', '.join(metadata[field])
      
      row.append(value)

    for field in structuredListFields:
      for fieldValue in structuredListFields[field]:
        value = False
        
        if type(metadata[field]) == list:
          value = fieldValue in metadata[field]
        
        row.append(value)  
        
with open('metadata.csv', 'w', newline='') as f:
  writer = csv.writer(f)
  writer.writerow(header)
  writer.writerows(data)
  


