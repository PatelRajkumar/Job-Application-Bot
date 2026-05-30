const puppeteer = require('puppeteer');
const path = require('path');

(async () => {
    // Process CLI arguments or fallback to defaults
    const inputFile = process.argv[2] || 'PurveshGandhi_Resume.html';
    const outputFile = process.argv[3] || 'PurveshGandhi_Resume_Generated_v2.pdf';

    console.log(`Starting Puppeteer...`);
    // Launch headless browser
    const browser = await puppeteer.launch({
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--font-render-hinting=none',
            '--force-color-profile=srgb',
        ],
    });
    const page = await browser.newPage();

    // 8.5in × 96 DPI = 816px — matches the resume's CSS width exactly.
    // Without this, Linux headless Chrome picks a narrower default viewport
    // which causes the content to reflow and appear zoomed-in in the PDF.
    await page.setViewport({ width: 816, height: 1056, deviceScaleFactor: 1 });

    // Resolve the absolute path to the HTML file relative to where the script is run
    const filePath = path.resolve(process.cwd(), inputFile);

    console.log(`Loading HTML file: ${filePath}`);
    await page.goto(`file://${filePath}`, { waitUntil: 'networkidle0' });

    console.log(`Adjusting layout to perfectly fit one page...`);
    await page.evaluate(() => {
        const pageElement = document.querySelector('.page');
        if (!pageElement) return;

        // 11in total height - 1in total vertical padding (0.5in top + 0.5in bottom) = 10in content area
        // 1in = 96px, so 10in = 960px
        const targetContentHeight = 960; 

        function getContentHeight() {
            const originalHeight = pageElement.style.height;
            pageElement.style.height = 'auto';
            const rect = pageElement.getBoundingClientRect();
            pageElement.style.height = originalHeight || '11in';
            return rect.height - 96;
        }

        let multiplier = 1.0;
        let step = 0.02;
        let iter = 0;
        const maxIterations = 50;
        const root = document.documentElement;
        
        const baseFonts = {
            '--font-size-small': 10,
            '--font-size-base': 11,
            '--font-size-large': 12,
            '--font-size-huge': 24
        };
        
        function applyMultiplier(m) {
            for (const [prop, val] of Object.entries(baseFonts)) {
                root.style.setProperty(prop, `${val * m}pt`);
            }
            
            let style = document.getElementById('dynamic-spacing');
            if (!style) {
                style = document.createElement('style');
                style.id = 'dynamic-spacing';
                document.head.appendChild(style);
            }
            style.innerHTML = `
                .header { margin-bottom: ${12 * m}pt !important; }
                .name { margin-bottom: ${2 * m}pt !important; }
                .section-title { 
                    margin-top: ${8 * m}pt !important; 
                    margin-bottom: ${4 * m}pt !important; 
                    padding-bottom: ${2 * m}pt !important; 
                }
                .skills-list li { margin-bottom: ${2 * m}pt !important; }
                .subheading-item { margin-bottom: ${4 * m}pt !important; }
                .subheading-row.row-1 { margin-bottom: ${1 * m}pt !important; }
                .subheading-row.row-2 { margin-bottom: ${2 * m}pt !important; }
                .item-list { 
                    margin-top: ${1 * m}pt !important; 
                    margin-bottom: ${3 * m}pt !important; 
                }
                .item-list li { margin-bottom: ${1 * m}pt !important; }
                .project-heading { margin-bottom: ${2 * m}pt !important; }
            `;
        }

        let currentHeight = getContentHeight();
        
        while (iter < maxIterations) {
            if (currentHeight > targetContentHeight) {
                multiplier -= step;
            } else if (currentHeight < targetContentHeight - 25) {
                multiplier += step;
            } else {
                break;
            }
            
            if (multiplier < 0.8) { applyMultiplier(0.8); break; }
            if (multiplier > 1.25) { applyMultiplier(1.25); break; }
            
            applyMultiplier(multiplier);
            let newHeight = getContentHeight();
            
            if (Math.abs(newHeight - currentHeight) < 2 && step === 0.02) {
                step = 0.005;
            }
            currentHeight = newHeight;
            iter++;
        }
    });

    console.log(`Generating PDF...`);

    // Convert to PDF
    await page.pdf({
        path: outputFile,
        format: 'Letter',
        printBackground: true, // Preserve background colors/styles
        pageRanges: '1',       // Force strictly to 1 page
        margin: {
            top: 0,
            right: 0,
            bottom: 0,
            left: 0,
        }
    });

    await browser.close();
    console.log(`Successfully created: ${outputFile}`);
})();
