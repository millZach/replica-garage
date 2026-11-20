"""Take-apart level 3: the workshop build list, parts not built yet, and the exploded view of the workshop copy."""
import pytest

from conftest import read_json, run_blender, write_json
from test_end_to_end import BODY, accept

pytestmark = pytest.mark.blender

DOORS = '''import bpy


def build(ctx):
    me = bpy.data.meshes.new('door_l')
    x0, x1, y0, y1, z0, z1 = ctx.mm([500, 1500, -950, -900, 300, 1100])
    v = [(a, b, c) for a in (x0, x1) for b in (y0, y1) for c in (z0, z1)]
    me.from_pydata(v, [], [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)])
    door = bpy.data.objects.new('door_l', me)
    door.data.materials.append(ctx.material('body'))
    ctx.add(door, part='door_l', separable=True, pivot=ctx.part('door_l')['pivot'])   # pivot in mm
'''


def test_workshop_copy_and_parts_not_yet_built(blender, project):
    accept(project, 'body', BODY)
    accept(project, 'doors', DOORS, depends=['body'])
    vehicle = [{'assembly': 'body', 'version': 0, 'seats': []}]
    write_json(project / 'data' / 'build.json', vehicle)
    write_json(project / 'data' / 'build-workshop.json',
               vehicle + [{'assembly': 'doors', 'version': 0, 'seats': []}])
    write_json(project / 'data' / 'parts.json', [{'part': 'door_l', 'fixed_to': 'shell', 'pivot': [500, -925, 700],
                                                  'level': 3, 'basis': 'reconstructed', 'assembly': 'doors'}])
    r = run_blender(blender, None, 'assemble.py', '--project', project)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    r = run_blender(blender, None, 'assemble.py', '--project', project, '--build',
                    project / 'data' / 'build-workshop.json')
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert (project / 'out' / 'workshop.blend').is_file() and (project / 'out' / 'vehicle.blend').is_file()
    rnd = project / 'evidence' / 'round-01'
    # on the vehicle the door's assembly is not built: listed as such, and the gate does not fail
    r = run_blender(blender, project / 'out' / 'vehicle.blend', 'separation.py', '--project', project,
                    '--level', 3, '--out', rnd / 'vehicle-parts', '--no-render')
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert read_json(rnd / 'vehicle-parts' / 'separation.json')['parts'][0]['status'] == 'not built'
    # on the workshop copy it is built with its pivot, and the exploded view goes to exploded/
    r = run_blender(blender, project / 'out' / 'workshop.blend', 'separation.py', '--project', project,
                    '--level', 3, '--out', rnd / 'exploded', '--resolution', '32x20', '--samples', 1)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    part = read_json(rnd / 'exploded' / 'separation.json')['parts'][0]
    assert part['status'] == 'built' and part['own_object'] and part['pivot_ok']
    assert (rnd / 'exploded' / 'exploded.png').is_file()
