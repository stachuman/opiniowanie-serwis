# Claude Coding Rules for E-ink PDF Templates

## Core Rules (ALWAYS Follow)

### 1. No Dummy Implementations
- **NEVER** write placeholder code (`pass`, `TODO`, mock data, dummy returns)
- Every function must do exactly what its name promises
- Not ready? Raise `NotImplementedError("Specific feature")` instead

### 2. Keep It Simple
- Favor readable solutions over clever optimizations
- One responsibility per function/class
- If you need comments to explain what code does, simplify the code first
- Avoid deep inheritance or complex abstractions

### 3. Validate Explicitly, Fail Fast
- **NEVER** silently default to arbitrary values
- **NEVER** assume what user wants with invalid input
- Always validate inputs and raise clear, specific exceptions
- If defaults needed, document them explicitly

### 4. Avoid Code Duplication
- Detect duplication → move to utilities or common class
- Reuse existing functionality when it makes sense
- Don't recreate what already exists

### 5. Challenge Incorrect Requests
- **ALWAYS** challenge if you believe request is wrong
- **PROPOSE** better alternatives with clear reasoning
- **EXPLAIN** why your approach is superior
- Don't blindly follow directions leading to poor outcomes

---

## Quick Guidelines

### Error Handling
```python
# GOOD: Explicit validation
if size < profile.constraints.min_font_pt:
    raise ValidationError(f"Font {size}pt below min {profile.constraints.min_font_pt}pt for '{profile.name}'")

# BAD: Silent fallback
return max(size, 10.0)  # Magic number!
```

### Naming
- **Functions:** verbs (`validate_template`, `render_pdf`, `create_bookmark`)
- **Modules:** nouns (`schema.py`, `renderer.py`, `validation.py`)
- **Be descriptive:** `convert_yaml_coordinates_to_pdf()` not `convert_coords()`

### Imports
```python
# 1. Standard library
import logging
from pathlib import Path

# 2. Third-party
import yaml
from pydantic import BaseModel

# 3. Local
from einkpdf.core.schema import Template
```

### Documentation
- Public functions → docstring with params/return
- Error messages → actionable (tell user how to fix)
- Complex logic → explanation comments

### Security
- Treat all YAML/user input as untrusted
- Validate file paths (prevent traversal attacks)
- Check file sizes before processing
- Never execute or eval user content

### Testing
- Test all error paths with clear, descriptive names
- Use real data (device profiles, fonts) not mocks
- Connect to running backend, don't create separate test scripts
- Use `manage-services.sh` for service management

---

## Project-Specific Rules

### Device Profiles
- All rendering functions must accept `DeviceProfile` parameter
- Never hardcode device-specific values
- Validate constraints before rendering

### Coordinate Systems
- Always specify coordinate system explicitly in signatures
- Convert at module boundaries only
- Never mix systems within one function

### Determinism
- Use fixed seeds for random operations
- Sort collections when order affects output
- Use consistent floating-point precision

---

## Rule Violations

If following these rules seems impossible:
1. **Stop** implementation
2. **Document** the specific conflict
3. **Propose** alternative approach
4. **Get approval** before proceeding

Never silently break rules.
