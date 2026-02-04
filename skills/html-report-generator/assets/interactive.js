/**
 * DeepMAST HTML Report Interactive Features
 *
 * JavaScript for tab navigation and pagination in CCI Analysis Reports
 * Compatible with Deep Interpreter Agent report generation
 */

/**
 * Tab Navigation Function
 *
 * Opens a specific tab and deactivates all others.
 *
 * @param {Event|null} evt - The click event (can be null for programmatic calls)
 * @param {string} tabName - The ID of the tab content to show
 *
 * Usage in HTML:
 * <button class="tab-button" onclick="openTab(event, 'part1')">Part 1</button>
 * <div id="part1" class="tab-content">...</div>
 */
function openTab(evt, tabName) {
    var i, tabcontent, tabbuttons;

    // Hide all tab content
    tabcontent = document.getElementsByClassName("tab-content");
    for (i = 0; i < tabcontent.length; i++) {
        tabcontent[i].style.display = "none";
        tabcontent[i].classList.remove("active");
    }

    // Remove active class from all tab buttons
    tabbuttons = document.getElementsByClassName("tab-button");
    for (i = 0; i < tabbuttons.length; i++) {
        tabbuttons[i].classList.remove("active");
    }

    // Show the selected tab content
    document.getElementById(tabName).style.display = "block";
    document.getElementById(tabName).classList.add("active");

    // Add active class to the clicked button (if event exists)
    if (evt) {
        evt.currentTarget.classList.add("active");
    }
}

/**
 * Pagination Function for L-R Interaction Tables
 *
 * Shows a specific page of interactions and highlights the active page button.
 *
 * @param {number} pageNum - The page number to display (1-indexed)
 *
 * Usage in HTML:
 * <div class="pagination">
 *   <button class="page-button" onclick="showPage(1)">1</button>
 *   <button class="page-button" onclick="showPage(2)">2</button>
 * </div>
 * <div id="interactions-page-1" class="interactions-page">...</div>
 * <div id="interactions-page-2" class="interactions-page">...</div>
 */
function showPage(pageNum) {
    var i, pages, buttons;

    // Hide all pages
    pages = document.getElementsByClassName("interactions-page");
    for (i = 0; i < pages.length; i++) {
        pages[i].style.display = "none";
        pages[i].classList.remove("active");
    }

    // Remove active class from all page buttons
    buttons = document.getElementsByClassName("page-button");
    for (i = 0; i < buttons.length; i++) {
        buttons[i].classList.remove("active");
    }

    // Show the selected page
    var targetPage = document.getElementById("interactions-page-" + pageNum);
    if (targetPage) {
        targetPage.style.display = "block";
        targetPage.classList.add("active");
    }

    // Highlight the active page button (0-indexed)
    if (buttons[pageNum - 1]) {
        buttons[pageNum - 1].classList.add("active");
    }
}

/**
 * Initialize report on page load
 *
 * - Opens the first tab (Part 1) by default
 * - Shows the first page of interactions if pagination exists
 */
document.addEventListener('DOMContentLoaded', function() {
    // Open first tab by default
    openTab(null, 'part1');

    // Initialize pagination if it exists
    if (document.getElementById("interactions-page-1")) {
        showPage(1);
    }
});
