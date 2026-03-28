import Foundation
import Vision
import AppKit
import PDFKit

func recognizeText(from cgImage: CGImage) -> String {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true

    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    do {
        try handler.perform([request])
    } catch {
        return ""
    }

    let observations = request.results as? [VNRecognizedTextObservation] ?? []
    let strings = observations.compactMap { $0.topCandidates(1).first?.string }
    return strings.joined(separator: "\n")
}

func renderPDFPage(_ page: PDFPage) -> CGImage? {
    let bounds = page.bounds(for: .mediaBox)
    let width = max(Int(bounds.width * 2), 1)
    let height = max(Int(bounds.height * 2), 1)
    guard
        let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
        let context = CGContext(
            data: nil,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: 0,
            space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        )
    else {
        return nil
    }

    context.setFillColor(NSColor.white.cgColor)
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    context.saveGState()
    context.scaleBy(x: 2.0, y: 2.0)
    page.draw(with: .mediaBox, to: context)
    context.restoreGState()
    return context.makeImage()
}

func ocrPDF(at path: String) -> String {
    guard let document = PDFDocument(url: URL(fileURLWithPath: path)) else {
        return ""
    }
    var pages: [String] = []
    let limit = min(document.pageCount, 5)
    for index in 0..<limit {
        guard let page = document.page(at: index), let image = renderPDFPage(page) else {
            continue
        }
        let text = recognizeText(from: image)
        if !text.isEmpty {
            pages.append(text)
        }
    }
    return pages.joined(separator: "\n")
}

func ocrImage(at path: String) -> String {
    guard let image = NSImage(contentsOfFile: path) else {
        return ""
    }
    var rect = CGRect(origin: .zero, size: image.size)
    guard let cgImage = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
        return ""
    }
    return recognizeText(from: cgImage)
}

guard CommandLine.arguments.count >= 2 else {
    exit(1)
}

let path = CommandLine.arguments[1]
let suffix = URL(fileURLWithPath: path).pathExtension.lowercased()
let text: String

if suffix == "pdf" {
    text = ocrPDF(at: path)
} else {
    text = ocrImage(at: path)
}

print(text)
