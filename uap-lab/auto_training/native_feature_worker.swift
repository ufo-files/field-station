import Foundation
import Vision
import CoreML
struct Input: Decodable { let id: String; let images: [String] }
func emit(_ value:[String:Any]) throws {
 var data=try JSONSerialization.data(withJSONObject:value,options:[.sortedKeys]);data.append(10);FileHandle.standardOutput.write(data)
}
do {
 guard CommandLine.arguments.count==3 else {throw NSError(domain:"Usage: crop_worker compiled_model version",code:1)}
 let config=MLModelConfiguration();config.computeUnits = .all
 let start=DispatchTime.now().uptimeNanoseconds
 let model=try VNCoreMLModel(for:MLModel(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1]),configuration:config))
 let version=CommandLine.arguments[2]
 try emit(["ready":true,"version":version,"model_load_seconds":Double(DispatchTime.now().uptimeNanoseconds-start)/1e9])
 while let line=readLine() {
  do {
   guard line.utf8.count<=32*1024*1024 else {throw NSError(domain:"Request too large",code:2)}
   let input=try JSONDecoder().decode(Input.self,from:Data(line.utf8))
   guard input.id.utf8.count<=256 && input.images.count<=256 else {throw NSError(domain:"Invalid request size",code:3)}
   var results:[[String:Any]]=[]
   for (index,encoded) in input.images.enumerated() {
    let tick=DispatchTime.now().uptimeNanoseconds
    do {
     guard encoded.utf8.count<=4*1024*1024,let bytes=Data(base64Encoded:encoded) else {throw NSError(domain:"Invalid crop data",code:4)}
     let request=VNCoreMLRequest(model:model);request.imageCropAndScaleOption = .scaleFill
     try VNImageRequestHandler(data:bytes,options:[:]).perform([request])
     guard let observations=request.results as? [VNCoreMLFeatureValueObservation], let vector=observations.first?.featureValue.multiArrayValue else {throw NSError(domain:"Missing native features",code:5)}
     let features=(0..<vector.count).map {vector[$0].doubleValue}
     results.append(["index":index,"features":features,"seconds":Double(DispatchTime.now().uptimeNanoseconds-tick)/1e9])
    } catch {results.append(["index":index,"error":error.localizedDescription,"seconds":Double(DispatchTime.now().uptimeNanoseconds-tick)/1e9])}
   }
   try emit(["id":input.id,"version":version,"results":results])
  } catch {try emit(["error":error.localizedDescription,"version":version])}
 }
} catch {FileHandle.standardError.write(Data((error.localizedDescription+"\n").utf8));exit(1)}
