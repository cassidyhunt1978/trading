// Unified Modal System
// Handles all modals with consistent API and lifecycle events

class ModalManager {
    constructor() {
        this.currentModal = null;
        this.modalHandlers = new Map();
    }

    /**
     * Register a modal with custom initialization logic
     * @param {string} modalId - The modal's data-modal attribute value
     * @param {Object} handlers - { onOpen, onClose, onInit }
     */
    register(modalId, handlers = {}) {
        this.modalHandlers.set(modalId, handlers);
    }

    /**
     * Open a modal by its ID
     * @param {string} modalId - The modal's data-modal attribute value
     * @param {Object} options - Data to pass to the modal
     */
    async open(modalId, options = {}) {
        const modal = document.querySelector(`[data-modal="${modalId}"]`);
        if (!modal) {
            console.error(`Modal not found: ${modalId}`);
            return;
        }

        // Close current modal if any
        if (this.currentModal && this.currentModal !== modal) {
            await this.close(this.currentModal.dataset.modal);
        }

        this.currentModal = modal;
        modal.classList.add('active');
        document.body.style.overflow = 'hidden'; // Prevent background scroll

        // Fire open event
        const event = new CustomEvent('modal:open', { detail: options });
        modal.dispatchEvent(event);

        // Call custom onOpen handler if registered
        const handlers = this.modalHandlers.get(modalId);
        if (handlers?.onOpen) {
            await handlers.onOpen(modal, options);
        }
    }

    /**
     * Close a modal by its ID (or close current modal if no ID provided)
     * @param {string} modalId - Optional modal ID, uses current if not provided
     */
    async close(modalId = null) {
        const modal = modalId 
            ? document.querySelector(`[data-modal="${modalId}"]`)
            : this.currentModal;
            
        if (!modal) return;

        modal.classList.remove('active');
        document.body.style.overflow = ''; // Restore scroll

        // Fire close event
        const event = new CustomEvent('modal:close');
        modal.dispatchEvent(event);

        // Call custom onClose handler if registered
        const handlers = this.modalHandlers.get(modal.dataset.modal);
        if (handlers?.onClose) {
            await handlers.onClose(modal);
        }

        if (this.currentModal === modal) {
            this.currentModal = null;
        }
    }

    /**
     * Close modal when clicking overlay (outside content)
     * @param {Event} event - Click event
     * @param {string} modalId - Modal ID to close
     */
    closeOnOverlay(event, modalId) {
        if (event.target === event.currentTarget) {
            this.close(modalId);
        }
    }

    /**
     * Initialize all modals on page load
     */
    initAll() {
        // Setup overlay click handlers for all modals
        document.querySelectorAll('[data-modal]').forEach(modal => {
            const overlay = modal.querySelector('.modal-overlay, [data-modal-overlay]');
            if (overlay) {
                overlay.addEventListener('click', (e) => {
                    this.closeOnOverlay(e, modal.dataset.modal);
                });
            }
        });

        // ESC key to close
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.currentModal) {
                this.close();
            }
        });

        // Call custom init handlers
        this.modalHandlers.forEach((handlers, modalId) => {
            if (handlers.onInit) {
                const modal = document.querySelector(`[data-modal="${modalId}"]`);
                if (modal) handlers.onInit(modal);
            }
        });
    }
}

// Create global instance
window.modalManager = new ModalManager();

// Convenience functions for backward compatibility
window.openModal = (modalId, options) => window.modalManager.open(modalId, options);
window.closeModal = (modalId) => window.modalManager.close(modalId);

// Initialize on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => window.modalManager.initAll());
} else {
    window.modalManager.initAll();
}
