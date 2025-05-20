import os
import sys
import glob
import yaml
from flask import Flask, render_template, request

# Import ACT API
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from act.act_model import ACTModel
from act.core.bom import load_bom
from act.core.units import units, year
from act.core.common import EnergyLocation, LogicProcess, DRAMProcess, SSDProcess

app = Flask(__name__)

# Assuming this script is in /frontend/app.py
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BOMS_DIR = os.path.join(PROJECT_ROOT, 'act', 'boms')

def get_bom_files():
    """Scans the BOMS_DIR for .yaml files."""
    bom_files = []
    if os.path.exists(BOMS_DIR):
        bom_files = [os.path.basename(f) for f in glob.glob(os.path.join(BOMS_DIR, '*.yaml'))]
    return bom_files

@app.route('/', methods=['GET', 'POST'])
def index():
    # Instantiate ACTModel with the shared_materials_model
    model = ACTModel()
    report_data = None
    error_message = None
    # Only allow supported logic, dram, and ssd processes in the dropdowns
    supported_logic_process_names = [
        'N28', 'N20', 'N14', 'N10', 'N8', 'N7', 'N5', 'N3'
    ]
    supported_dram_process_names = [
        'DDR3_50NM', 'DDR3_40NM', 'DDR3_30NM', 'LPDDR3_30NM', 'LPDDR3_20NM', 'LPDDR2_20NM', 'LPDDR4', 'DDR4_10NM'
    ]
    supported_ssd_process_names = [
        'NAND_30NM', 'NAND_20NM', 'NAND_10NM', 'NAND_TLC_1Z', 'NAND_TLC_V3',
        'SEAGATE_3530', 'SEAGATE_1551', 'SEAGATE_3331',
        'WD_2016', 'WD_2017', 'WD_2018', 'WD_2019'
    ]
    logic_processes = [(p.name, p.value) for p in LogicProcess if p.name in supported_logic_process_names]
    dram_processes = [(p.name, p.value) for p in DRAMProcess if p.name in supported_dram_process_names]
    ssd_processes = [(p.name, p.value) for p in SSDProcess if p.name in supported_ssd_process_names]
    # Material type/category options (for demo, you can expand as needed)
    material_categories = [
        ('FRAME', 'Frame'),
        ('ENCLOSURE', 'Enclosure'),
        ('PCB', 'PCB'),
        ('BATTERY', 'Battery'),
    ]
    # Dynamically build allowed material types from the enum (excluding NA)
    material_types = []
    for member in model.materials_model.MaterialType: # Iterate directly over the Enum
        if member.name != 'NA':
            material_types.append((member.name, member.value.title()))

    user_input = {
        'logic_area': request.form.get('logic_area', '100 mm2'),
        'logic_process': request.form.get('logic_process', logic_processes[0][0]),
        'dram_capacity': request.form.get('dram_capacity', '16 GB'),
        'dram_process': request.form.get('dram_process', dram_processes[0][0]),
        'ssd_capacity': request.form.get('ssd_capacity', '512 GB'),
        'ssd_process': request.form.get('ssd_process', ssd_processes[0][0]),
        'op_power': request.form.get('op_power', '100 W'),
        'duty_cycle': request.form.get('duty_cycle', '1.0'),
        'hw_lifetime': request.form.get('hw_lifetime', '2 year'),
        'op_ci': request.form.get('op_ci', 'USA'),
        'material_name': request.form.get('material_name', ''),
        'material_category': request.form.get('material_category', material_categories[0][0]),
        # Ensure material_types is not empty before accessing its first element
        'material_type': request.form.get('material_type', material_types[0][0] if material_types else ''),
        'material_weight': request.form.get('material_weight', ''),
    }

    # For multiple materials, parse lists from the form
    material_names = request.form.getlist('material_name')
    material_categories_input = request.form.getlist('material_category')
    material_types_input = request.form.getlist('material_type')
    material_weights = request.form.getlist('material_weight')
    user_input.update({
        'material_names': material_names,
        'material_categories': material_categories_input,
        'material_types': material_types_input,
        'material_weights': material_weights,
    })

    if request.method == 'POST':
        try:
            from act.core.common import ModelType, EnergyLocation, ComponentCategory
            from act.core.bom import BOM
            from act.core.units import units, year

            # Build a minimal BOM from user input
            logic_process = LogicProcess[user_input['logic_process']]
            dram_process = DRAMProcess[user_input['dram_process']]
            ssd_process = SSDProcess[user_input['ssd_process']]
            silicon = {
                'logic': {
                    'model': ModelType.LOGIC.value,
                    'area': user_input['logic_area'],
                    'process': logic_process,
                    'n_ics': 1,
                },
                'dram': {
                    'model': ModelType.DRAM.value,
                    'capacity': user_input['dram_capacity'],
                    'process': dram_process,
                    'n_ics': 1,
                },
                'ssd': {
                    'model': ModelType.FLASH.value,
                    'capacity': user_input['ssd_capacity'],
                    'process': ssd_process,
                    'n_ics': 1,
                },
            }
            materials = {}
            for name, cat, typ_name, wt in zip(material_names, material_categories_input, material_types_input, material_weights):
                if name and wt:
                    try:
                        # typ_name is 'STEEL' (name from form)
                        # Access enum member by its name using getattr
                        mat_type = getattr(model.materials_model.MaterialType, typ_name)
                    except (KeyError, AttributeError):
                        # Fallback or error handling if typ_name is not a valid member name
                        app.logger.warning(f"Invalid material type name: {typ_name}. Skipping.")
                        continue
                    if mat_type.name == 'NA': # Check name for NA
                        continue  # skip NA types
                    materials[name] = {
                        'category': ComponentCategory[cat].value,
                        'type': mat_type,  # Use the enum member itself
                        'weight': wt,
                    }
            # Instantiate BOM with the shared material_type_enum
            bom_instance = BOM(silicon=silicon, materials=materials, material_type=model.materials_model.MaterialType)

            # Parse other parameters
            op_power = units(user_input['op_power'])
            duty_cycle = float(user_input['duty_cycle'])
            hw_lifetime = units(user_input['hw_lifetime'])
            op_ci = getattr(EnergyLocation, user_input['op_ci']) if hasattr(EnergyLocation, user_input['op_ci']) else EnergyLocation.USA

            # Pass the BOM instance directly
            total_carbon = model.get_carbon(bom=bom_instance, op_power=op_power, op_ci=op_ci, duty_cycle=duty_cycle, hw_lifetime=hw_lifetime)
            report_data = {
                'total_carbon': str(total_carbon.total()),
                'by_category': {src.name: str(total_carbon.partial(src)) for src in total_carbon.carbon_by_type},
            }
        except Exception as e:
            error_message = f"Error running ACT model: {e}"

    return render_template('index.html', report_data=report_data, error_message=error_message, user_input=user_input, logic_processes=logic_processes, dram_processes=dram_processes, ssd_processes=ssd_processes, material_categories=material_categories, material_types=material_types)

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
    app.run(debug=True)
