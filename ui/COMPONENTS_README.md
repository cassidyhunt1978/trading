# UI Component Architecture

## Directory Structure

```
ui/
 templates/
   ├── index.html                  # Main layout (navigation + includes)
   ├── components/
   │   ├── macros.html            # Reusable component macros
   │   ├── nav.html               # Main navigation bar
   │   ├── stat_card.html         # Stat card template (alternative)
   │   ├── tab_header.html        # Tab header template (alternative)
   │   ├── loading_state.html     # Loading state template (alternative)
   │   └── filter_buttons.html    # Filter button group (alternative)
   ├── tabs/
   │   ├── portfolio.html         # Uses macros: stat_card, tab_header, filter_button
   │   ├── symbols.html           # Uses macros: loading_state
   │   ├── strategies.html        # To be refactored
   │   ├── policies.html          # To be refactored
   │   └── system.html            # To be refactored
   └── modals/
       ├── modal_overlay.html     # Main modal container
       └── ensemble_backtest.html # Ensemble backtest modal
 css/
   └── app.css                    # External styles
 js/
    ├── config.js                  # Global configuration
    ├── app-utils.js               # Utilities (toast, modals)
    ├── tabs.js                    # Tab switching
    └── init.js                    # Initialization
```

## Component Macros

### Import Macros
```jinja2
{% from 'components/macros.html' import stat_card, tab_header, action_button, filter_button, table_wrapper, gradient_card, loading_state %}
```

### Available Macros

#### 1. stat_card(label, value_id, value='-', color='')
Simple stat card with label and dynamic value.

**Usage:**
```jinja2
{{ stat_card('Open Positions', 'open-count') }}
{{ stat_card('Total P&L', 'total-pnl', value='$0', color='text-green-400') }}
```

#### 2. tab_header(title)
Tab header with title and action buttons (uses caller).

**Usage:**
```jinja2
{% call tab_header('Portfolio & Positions') %}
    {{ action_button('🔄 Refresh', 'loadPositions()') }}
    {{ action_button('+ New', 'createPosition()', classes='bg-green-600 hover:bg-green-700 px-4 py-2 rounded-lg') }}
{% endcall %}
```

#### 3. action_button(text, onclick, classes='...')
Reusable action button.

**Usage:**
```jinja2
{{ action_button('🔄 Refresh', 'loadData()') }}
{{ action_button('Delete', 'deleteItem()', classes='bg-red-600 hover:bg-red-700 px-3 py-1 rounded text-sm') }}
```

#### 4. filter_button(id, label, onclick, active=false)
Filter button with active state.

**Usage:**
```jinja2
{{ filter_button('filter-all', 'All', "filterItems('all')", active=true) }}
{{ filter_button('filter-open', 'Open', "filterItems('open')") }}
```

#### 5. table_wrapper()
Table container with styling (uses caller for table content).

**Usage:**
```jinja2
{% call table_wrapper() %}
    <thead>
        <tr><th>Column 1</th><th>Column 2</th></tr>
    </thead>
    <tbody id="table-body">
        <tr><td>Loading...</td></tr>
    </tbody>
{% endcall %}
```

#### 6. gradient_card(from_color='purple-900', to_color='purple-800', border_color='purple-500')
Gradient card for special sections (uses caller).

**Usage:**
```jinja2
{% call gradient_card() %}
    <h3>Special Section</h3>
    <p>Content here</p>
{% endcall %}

{% call gradient_card(from_color='blue-900', to_color='blue-800', border_color='blue-500') %}
    <h3>Custom Colors</h3>
{% endcall %}
```

#### 7. loading_state(message='Loading...', icon='⏳', colspan=none)
Loading state indicator for tables or grids.

**Usage:**
```jinja2
<!-- For grids -->
{{ loading_state('Loading symbols...') }}

<!-- For tables -->
{{ loading_state('Fetching data...', icon='🔄', colspan=10) }}
```

## Refactoring Examples

### Before (Repetitive HTML):
```html
<div class="bg-gray-800 p-4 rounded-lg">
    <div class="text-gray-400 text-sm mb-1">Open Positions</div>
    <div class="text-2xl font-bold" id="open-count">-</div>
</div>
<div class="bg-gray-800 p-4 rounded-lg">
    <div class="text-gray-400 text-sm mb-1">Closed Today</div>
    <div class="text-2xl font-bold" id="closed-today">-</div>
</div>
```

### After (Using Components):
```jinja2
{{ stat_card('Open Positions', 'open-count') }}
{{ stat_card('Closed Today', 'closed-today') }}
```

## Benefits

1. **DRY Principle**: No repeated HTML patterns
2. **Maintainability**: Update component in one place, changes everywhere
3. **Consistency**: All instances use same structure and styling
4. **Readability**: Less code, clearer intent
5. **Flexibility**: Parameters allow customization
6. **API-like**: Similar modular approach as backend services

## Next Steps

- [ ] Refactor strategies.html to use components
- [ ] Refactor policies.html to use components  
- [ ] Refactor system.html to use components
- [ ] Create additional macros as patterns emerge
- [ ] Add component documentation comments
