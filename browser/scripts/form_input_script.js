/*
 * Form Input Script for Job Agent
 * Smart form filling that handles all input types natively.
 */

(function (elementRef, inputValue) {
    try {
        // Get element from reference map
        let element = null;

        if (window.__elementMap && window.__elementMap[elementRef]) {
            const weakRef = window.__elementMap[elementRef];
            element = weakRef.deref() || null;

            if (!element || !document.contains(element)) {
                delete window.__elementMap[elementRef];
                element = null;
            }
        }

        if (!element) {
            return {
                success: false,
                message: `No element found with ref: "${elementRef}". Call get_page_elements() to refresh.`
            };
        }

        // Scroll element into view
        element.scrollIntoView({ behavior: 'instant', block: 'center' });

        // Handle SELECT dropdowns
        if (element instanceof HTMLSelectElement) {
            const previousValue = element.value;
            const options = Array.from(element.options);

            // Try to find option by value or text
            let optionFound = false;
            const valueStr = String(inputValue).toLowerCase();

            for (let i = 0; i < options.length; i++) {
                if (options[i].value.toLowerCase() === valueStr ||
                    options[i].text.toLowerCase().includes(valueStr)) {
                    element.selectedIndex = i;
                    optionFound = true;
                    break;
                }
            }

            if (!optionFound) {
                const available = options.slice(0, 10).map(o => `"${o.text}"`).join(', ');
                return {
                    success: false,
                    message: `Option "${inputValue}" not found. Available: ${available}${options.length > 10 ? '...' : ''}`
                };
            }

            element.focus();
            element.dispatchEvent(new Event('change', { bubbles: true }));
            element.dispatchEvent(new Event('input', { bubbles: true }));

            return {
                success: true,
                type: 'select',
                previous: previousValue,
                current: element.value,
                message: `Selected "${element.options[element.selectedIndex].text}"`
            };
        }

        // Handle CHECKBOX
        if (element instanceof HTMLInputElement && element.type === 'checkbox') {
            const previousValue = element.checked;

            // Accept boolean or truthy/falsy values
            const newValue = inputValue === true || inputValue === 'true' || inputValue === 1;
            element.checked = newValue;

            element.focus();
            element.dispatchEvent(new Event('change', { bubbles: true }));
            element.dispatchEvent(new Event('input', { bubbles: true }));

            return {
                success: true,
                type: 'checkbox',
                previous: previousValue,
                current: element.checked,
                message: `Checkbox ${element.checked ? 'checked' : 'unchecked'}`
            };
        }

        // Handle RADIO
        if (element instanceof HTMLInputElement && element.type === 'radio') {
            const previousValue = element.checked;
            element.checked = true;

            element.focus();
            element.dispatchEvent(new Event('change', { bubbles: true }));
            element.dispatchEvent(new Event('input', { bubbles: true }));

            return {
                success: true,
                type: 'radio',
                previous: previousValue,
                current: true,
                message: `Radio button selected${element.name ? ` in group "${element.name}"` : ''}`
            };
        }

        // Handle DATE/TIME inputs
        if (element instanceof HTMLInputElement &&
            ['date', 'time', 'datetime-local', 'month', 'week'].includes(element.type)) {
            const previousValue = element.value;
            element.value = String(inputValue);

            element.focus();
            element.dispatchEvent(new Event('change', { bubbles: true }));
            element.dispatchEvent(new Event('input', { bubbles: true }));

            return {
                success: true,
                type: element.type,
                previous: previousValue,
                current: element.value,
                message: `Set ${element.type} to "${element.value}"`
            };
        }

        // Handle NUMBER/RANGE inputs
        if (element instanceof HTMLInputElement &&
            ['number', 'range'].includes(element.type)) {
            const previousValue = element.value;
            const numValue = Number(inputValue);

            if (isNaN(numValue)) {
                return {
                    success: false,
                    message: `${element.type} input requires a number, got "${inputValue}"`
                };
            }

            element.value = String(numValue);
            element.focus();
            element.dispatchEvent(new Event('change', { bubbles: true }));
            element.dispatchEvent(new Event('input', { bubbles: true }));

            return {
                success: true,
                type: element.type,
                previous: previousValue,
                current: element.value,
                message: `Set to ${element.value}`
            };
        }

        // Handle TEXT inputs and TEXTAREA
        if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
            const previousValue = element.value;
            element.value = String(inputValue);

            element.focus();
            // Set cursor to end
            element.setSelectionRange(element.value.length, element.value.length);

            element.dispatchEvent(new Event('change', { bubbles: true }));
            element.dispatchEvent(new Event('input', { bubbles: true }));

            const elType = element instanceof HTMLTextAreaElement ? 'textarea' : (element.type || 'text');

            return {
                success: true,
                type: elType,
                previous: previousValue,
                current: element.value,
                message: `Set ${elType} to "${element.value.substring(0, 30)}${element.value.length > 30 ? '...' : ''}"`
            };
        }

        // Handle contenteditable elements
        if (element.getAttribute('contenteditable') === 'true') {
            const previousValue = element.textContent;
            element.textContent = String(inputValue);

            element.focus();
            element.dispatchEvent(new Event('input', { bubbles: true }));

            return {
                success: true,
                type: 'contenteditable',
                previous: previousValue,
                current: element.textContent,
                message: `Set content to "${inputValue.substring(0, 30)}..."`
            };
        }

        return {
            success: false,
            message: `Element type "${element.tagName}" is not a supported form input`
        };
    } catch (error) {
        return {
            success: false,
            message: `Error setting form value: ${error.message || 'Unknown error'}`
        };
    }
})
