/*
 * Element Reference Script for Job Agent
 * Provides stable element references using WeakRef that survive DOM updates.
 */

(function (elementRef) {
    try {
        // Get element from reference map
        let targetElement = null;

        if (window.__elementMap && window.__elementMap[elementRef]) {
            const weakRef = window.__elementMap[elementRef];
            targetElement = weakRef.deref() || null;

            if (!targetElement || !document.contains(targetElement)) {
                // Element has been removed from DOM
                delete window.__elementMap[elementRef];
                targetElement = null;
            }
        }

        if (!targetElement) {
            return {
                success: false,
                message: `No element found with ref: "${elementRef}". Element may have been removed from page. Call get_page_elements() to refresh.`
            };
        }

        // Scroll element into view if needed
        targetElement.scrollIntoView({ behavior: 'instant', block: 'center', inline: 'center' });

        // Force layout to ensure element is properly positioned after scroll
        targetElement.offsetHeight;

        // Get element coordinates
        const rect = targetElement.getBoundingClientRect();
        const x = Math.round(rect.left + rect.width / 2);
        const y = Math.round(rect.top + rect.height / 2);

        // Get element info
        const tag = targetElement.tagName.toLowerCase();
        const id = targetElement.id || '';
        const text = (targetElement.textContent || '').trim().substring(0, 50);
        const type = targetElement.getAttribute('type') || '';
        const role = targetElement.getAttribute('role') || '';
        const placeholder = targetElement.getAttribute('placeholder') || '';
        const value = targetElement.value || '';

        // Check visibility
        const style = window.getComputedStyle(targetElement);
        const isVisible = rect.width > 0 && rect.height > 0 &&
            style.visibility !== 'hidden' &&
            style.display !== 'none';

        // Check if interactable
        const isInteractable = !targetElement.disabled && isVisible;

        // Detect if it's a dropdown/expandable
        const isDropdown = targetElement.getAttribute('aria-haspopup') === 'true' ||
            targetElement.getAttribute('aria-expanded') !== null ||
            ['combobox', 'listbox', 'menu', 'menubutton'].includes(role) ||
            tag === 'select';

        const isExpanded = targetElement.getAttribute('aria-expanded') === 'true';

        return {
            success: true,
            ref: elementRef,
            x: x,
            y: y,
            tag: tag,
            id: id,
            text: text,
            type: type,
            role: role,
            placeholder: placeholder,
            value: value,
            isVisible: isVisible,
            isInteractable: isInteractable,
            isDropdown: isDropdown,
            isExpanded: isExpanded,
            rect: {
                left: Math.round(rect.left),
                top: Math.round(rect.top),
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            }
        };
    } catch (error) {
        return {
            success: false,
            message: 'Error finding element: ' + (error.message || 'Unknown error')
        };
    }
})
