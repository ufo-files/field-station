import Foundation
import Vision
import CoreML

struct Input: Decodable { let images: [String]; let use_custom: Bool?; let policy_path: String? }
struct Label: Codable {
    let identifier: String; let confidence: Float
    var source: String? = nil; var threshold: Float? = nil
    var minimum_native_size: Float? = nil; var model_version: String? = nil
}
struct Result: Codable { let labels: [Label]; let error: String? }
struct Output: Codable { let engine: String; let model_version: String; let model_error: String?; let results: [Result] }
struct Active: Decodable { let version: String; let compiled_path: String; let thresholds: [String:Float]; let minimum_native_size: Float }

do {
    if CommandLine.arguments.count == 4 && CommandLine.arguments[1] == "--compile" {
        let source=URL(fileURLWithPath:CommandLine.arguments[2]), target=URL(fileURLWithPath:CommandLine.arguments[3])
        if !FileManager.default.fileExists(atPath:target.path) {
            let compiled=try MLModel.compileModel(at:source)
            try FileManager.default.copyItem(at:compiled,to:target)
        }
        print("compiled");exit(0)
    }
    let bytes=FileHandle.standardInput.readDataToEndOfFile()
    guard bytes.count<=12_000_000 else { throw NSError(domain:"Input too large",code:1) }
    let input=try JSONDecoder().decode(Input.self,from:bytes)
    guard input.images.count<=24 else { throw NSError(domain:"Too many crops",code:2) }
    let directory=URL(fileURLWithPath:CommandLine.arguments[0]).deletingLastPathComponent()
    let compiled=directory.appendingPathComponent("YOLOv3FP16.mlmodelc")
    if !FileManager.default.fileExists(atPath:compiled.path) {
        let temporary=try MLModel.compileModel(at:directory.appendingPathComponent("YOLOv3FP16.mlmodel"))
        try FileManager.default.copyItem(at:temporary,to:compiled)
    }
    let configuration=MLModelConfiguration();configuration.computeUnits = .all
    let model=try VNCoreMLModel(for:MLModel(contentsOf:compiled,configuration:configuration))
    var active:Active?=nil, custom:VNCoreMLModel?=nil, modelError:String?=nil
    if input.use_custom != false {
        let config=input.policy_path.map { URL(fileURLWithPath:$0) } ?? directory.appendingPathComponent("active-model.json")
        if FileManager.default.fileExists(atPath:config.path) {
            do {
                active=try JSONDecoder().decode(Active.self,from:Data(contentsOf:config))
                custom=try VNCoreMLModel(for:MLModel(contentsOf:URL(fileURLWithPath:active!.compiled_path),configuration:configuration))
            } catch { modelError=error.localizedDescription;active=nil }
        }
    }
    var results:[Result]=[]
    for encoded in input.images {
        do {
            guard let data=Data(base64Encoded:encoded) else { throw NSError(domain:"Invalid image",code:3) }
            let request=VNCoreMLRequest(model:model);request.imageCropAndScaleOption = .scaleFit
            let handler=VNImageRequestHandler(data:data,options:[:]);try handler.perform([request])
            let detections=(request.results as? [VNRecognizedObjectObservation]) ?? []
            var labels=detections.filter { $0.boundingBox.midX>0.1 && $0.boundingBox.midX<0.9 && $0.boundingBox.midY>0.1 && $0.boundingBox.midY<0.9 }.compactMap { $0.labels.first }.sorted { $0.confidence>$1.confidence }.prefix(12).map { Label(identifier:$0.identifier,confidence:$0.confidence) }
            if let trained=custom,let policy=active {
                let classify=VNCoreMLRequest(model:trained);classify.imageCropAndScaleOption = .scaleFill
                try handler.perform([classify])
                if let best=(classify.results as? [VNClassificationObservation])?.first,
                   let threshold=policy.thresholds[best.identifier],best.confidence>=threshold {
                    var result=Label(identifier:best.identifier,confidence:best.confidence)
                    result.source="camera-trained";result.threshold=threshold;result.minimum_native_size=policy.minimum_native_size;result.model_version=policy.version
                    labels.insert(result,at:0)
                }
            }
            results.append(Result(labels:labels,error:nil))
        } catch { results.append(Result(labels:[],error:error.localizedDescription)) }
    }
    let output=try JSONEncoder().encode(Output(engine:custom == nil ? "coreml-yolov3-fp16-coco":"camera-crop-mobilenet-v3",model_version:active?.version ?? "baseline-yolov3",model_error:modelError,results:results))
    FileHandle.standardOutput.write(output)
} catch { FileHandle.standardError.write(Data((error.localizedDescription+"\n").utf8));exit(1) }
