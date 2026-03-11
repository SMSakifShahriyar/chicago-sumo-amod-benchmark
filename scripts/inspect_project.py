from pathlib import Path

root = Path(__file__).resolve().parents[1]

print('Project root:', root)
print()
print('Folders and files:')
for p in sorted(root.rglob('*')):
    rel = p.relative_to(root)
    if p.is_dir():
        print(f'[DIR]  {rel}')
    else:
        size = p.stat().st_size
        print(f'[FILE] {rel} ({size} bytes)')

print()
osm_files = []
for p in root.rglob('*'):
    if not p.is_file():
        continue
    name = p.name.lower()
    if p.suffix.lower() in {'.osm', '.pbf'} or name.endswith('.osm.xml'):
        osm_files.append(p)
osm_files = sorted(osm_files)
if osm_files:
    print('OSM-like files found:')
    for p in osm_files:
        rel = p.relative_to(root)
        print(f'- {rel} ({p.stat().st_size} bytes)')
else:
    print('No OSM-like files found.')

print()
patterns = {
    'net_files': ['*.net.xml'],
    'sumocfg_files': ['*.sumocfg'],
    'route_files': ['*.rou.xml', '*.route.xml'],
    'additional_files': ['*.add.xml', '*.additional.xml']
}
for name, pats in patterns.items():
    found = []
    for pat in pats:
        found.extend(root.rglob(pat))
    found = sorted(set(found))
    print(name + ':')
    if found:
        for p in found:
            print('-', p.relative_to(root))
    else:
        print('- none')
