#include "experiment.hpp"

namespace layered_images {
Json read_json(const fs::path& path) {std::ifstream f(path);if(!f) fail("cannot read "+path.string());return Json::parse(f);}
void save_json(const fs::path& path,const Json& data) {std::ofstream f(path);f<<data.dump(2)<<'\n';if(!f)fail("cannot write JSON");}
void save_rgb(const fs::path& path,std::span<const std::uint32_t> pixels) {
    std::ofstream f(path,std::ios::binary);
    for(auto p:pixels) for(int shift:{16,8,0}) f.put(static_cast<char>((p>>shift)&255));
    if(!f)fail("cannot write RGB");
}
std::vector<std::uint32_t> load_rgb(const fs::path& path) {
    const auto bytes=read_file(path);if(bytes.size()%3)fail("invalid RGB size");
    std::vector<std::uint32_t> result(bytes.size()/3);
    for(std::size_t i=0;i<result.size();++i) result[i]=(std::uint32_t(bytes[i*3])<<16U)|(std::uint32_t(bytes[i*3+1])<<8U)|bytes[i*3+2];
    return result;
}
ViewTransform json_view(const Json& value) {
    const auto v=[&](std::string_view k){const auto& a=value.at(k);return Vec3{a[0],a[1],a[2]};};
    return {v("origin"),v("forward"),v("right"),v("up")};
}
Json view_json(const ViewTransform& v) {
    const auto a=[](Vec3 p){return Json::array({p.x,p.y,p.z});};
    return {{"origin",a(v.origin)},{"forward",a(v.forward)},{"right",a(v.screen_right)},{"up",a(v.up)}};
}
Json metrics(const Image& predicted,std::span<const std::uint32_t> target,
             std::span<const std::uint32_t> previous,std::span<const std::uint32_t> previous_target) {
    if(predicted.rgb.size()!=display_pixels || target.size()!=display_pixels || predicted.depth.size()!=display_pixels)
        fail("full-display metrics require 256x224 pixels");
    double error=0,temporal=0;std::size_t gaps=0;
    for(std::size_t p=0;p<target.size();++p) {
        gaps+=!std::isfinite(predicted.depth[p]);
        for(int shift:{16,8,0}) {
            const int residual=static_cast<int>((predicted.rgb[p]>>shift)&255)-static_cast<int>((target[p]>>shift)&255);
            error+=std::abs(residual);
            if(!previous.empty()) {
                const int old=static_cast<int>((previous[p]>>shift)&255)-static_cast<int>((previous_target[p]>>shift)&255);
                temporal+=std::abs(residual-old);
            }
        }
    }
    return {{"mae",error/(display_pixels*3)},{"gapFraction",static_cast<double>(gaps)/display_pixels},
        {"temporalResidualMae",temporal/(display_pixels*3)},{"samples",predicted.samples},{"fragments",predicted.fragments},
        {"retainedBytes",predicted.bytes}};
}
void evaluate_job(const fs::path& folder,const Json& variants,const fs::path& output,bool pictures) {
    const auto start=Clock::now();const auto c=load_capture(folder);fs::create_directories(output);
    Json rows=Json::array();
    std::vector<std::vector<std::uint32_t>> targets,baseline,baseline_mask,dynamic;
    const bool has_dynamic=c.metadata.at("job").value("dynamic",false);
    const bool export_native=std::any_of(variants.begin(),variants.end(),[](const Json& v){return v.value("nativeFragments",false);});
    const bool export_hdma=std::any_of(variants.begin(),variants.end(),[](const Json& v){return v.value("nativeHdma",false);});
    if(export_native) {
        native_palette.clear();native_palette.emplace(0,0);
        for(const auto& s:c.samples) if(s.depth>0) native_palette.emplace(s.rgb,0);
        if(native_palette.size()>256)fail("native palette exceeds 256 entries");
        std::vector<std::uint32_t> colors(256);std::uint16_t index=0;
        for(auto& [rgb,id]:native_palette){id=index;colors[index]=rgb;++index;}
        save_rgb(output/"palette.rgb",colors);
    }
    for(int age=0;age<10;++age) {
        if(export_hdma) {
            const WarpSettings settings{false,192,true,32,{213,205,437}};
            save_json(output/("hdma-"+std::to_string(age)+".json"),
                hdma_warp_json(hdma_camera_warp(json_view(c.metadata.at("targets")[age].at("view")),c.view,settings)));
        }
        targets.push_back(load_rgb(folder/("target-"+std::to_string(age)+".rgb")));
        baseline.push_back(load_rgb(folder/("baseline-"+std::to_string(age)+".rgb")));
        baseline_mask.push_back(load_rgb(folder/("baseline-mask-"+std::to_string(age)+".rgb")));
        if(has_dynamic) dynamic.push_back(load_rgb(folder/("dynamic-"+std::to_string(age)+".rgb")));
    }
    for(const auto& variant:variants) {
        const std::string name=variant.at("id");
        std::vector<std::uint32_t> previous=targets[0];
        for(std::size_t age=1;age<10;++age) {
            std::ofstream stream;
            if(variant.value("nativeFragments",false)) {
                stream.open(output/(name+"-"+std::to_string(age)+".fragments"),std::ios::binary);
                if(!stream)fail("cannot open native fragment stream");
                native_stream=&stream;
            }
            const auto frame_start=Clock::now();
            Image image;
            if(name=="baseline") {
                image.rgb=baseline[age];
                for(std::size_t p=0;p<image.depth.size();++p) if(baseline_mask[age][p]) image.depth[p]=1;
            } else image=reproject(c,json_view(c.metadata.at("targets")[age].at("view")),variant);
            const double elapsed=seconds(frame_start);
            native_stream=nullptr;
            auto m=metrics(image,targets[age],previous,targets[age-1]);
            m["variant"]=name;m["age"]=age;m["reprojectionSeconds"]=elapsed;
            if(has_dynamic) m["dynamic"]=metrics(image,dynamic[age],previous,dynamic[age-1]);
            rows.push_back(m);
            if(pictures) save_rgb(output/(name+"-"+std::to_string(age)+".rgb"),image.rgb);
            previous=std::move(image.rgb);
        }
    }
    save_json(output/"evaluation.json",{{"schema","layered-image-evaluation-v1"},{"job",c.metadata.at("job")},
        {"variants",variants},{"rows",rows},{"captureResidentBytes",c.samples.size()*sizeof(Sample)},
        {"elapsedSeconds",seconds(start)}});
}
void self_test() {
    Capture c;c.padding=0;c.density=1;c.layers=1;c.w=width;c.h=height;
    c.view={{0,0,0},{0,1,0},{1,0,0},{0,0,1}};
    c.samples.resize(width*height);c.source.resize(width*height);
    for(int y=0;y<height;++y)for(int x=0;x<width;++x) {
        const auto p=static_cast<std::size_t>(y*width+x);
        const auto rgb=static_cast<std::uint32_t>(1+x+y*width);
        c.samples[p]={100,{0,-1,0},rgb,0,0};c.source[p]=rgb;
    }
    const auto expected=present_x3(c.source,{});
    for(const std::string footprint:{"point","flat","gradient","plane-oracle"}) {
        const Json v={{"layers",1},{"padding",0},{"density",1},{"footprint",footprint}};
        const auto identity=reproject(c,c.view,v);
        if(identity.rgb!=expected)fail("identity reprojection "+footprint);
        auto moved=c.view;moved.origin.x=100.0/64;
        const auto translated=reproject(c,moved,v);
        std::vector<std::uint32_t> shifted(width*height);
        for(int y=0;y<height;++y)for(int x=0;x<width-1;++x)shifted[static_cast<std::size_t>(y*width+x)]=c.source[static_cast<std::size_t>(y*width+x+1)];
        if(translated.rgb!=present_x3(shifted,{}))fail("translation reprojection "+footprint);
    }
    Image black;const std::vector<std::uint32_t> white(display_pixels,0xffffff);
    const auto m=metrics(black,white,{},{});
    if(m.at("mae")!=255 || m.at("gapFraction")!=1)fail("black gaps must count as error");
    // A retained second layer must reveal old background, without overwriting
    // nearer foreground. This fixture has no freshly rendered target input.
    c.layers=2;c.samples.resize(width*height*2);
    for(int y=0;y<height;++y)for(int x=0;x<width;++x) {
        const auto p=static_cast<std::size_t>(y*width+x);
        const bool foreground=x>=30 && x<=54;
        c.samples[p]={foreground ? 100.F:200.F,{0,-1,0},foreground ? 0xff0000U:0xffffffU,0,0};
        c.samples[p+width*height]={foreground ? 200.F:0.F,{0,-1,0},0xffffff,1,0};
    }
    auto moved=c.view;moved.origin.x=10;
    Json v={{"layers",1},{"padding",0},{"density",1},{"footprint","flat"}};
    const auto one=reproject(c,moved,v);v["layers"]=2;
    const auto two=reproject(c,moved,v);
    if(std::count(one.rgb.begin(),one.rgb.end(),0U)<=std::count(two.rgb.begin(),two.rgb.end(),0U))
        fail("hidden background did not fill disocclusion");
    if(std::count(one.rgb.begin(),one.rgb.end(),0xff0000U)!=std::count(two.rgb.begin(),two.rgb.end(),0xff0000U))
        fail("hidden background overwrote foreground");
}
} // namespace layered_images

int main(int argc,char** argv) {
    const auto start=layered_images::Clock::now();
    try {
        CLI::App app{"Isolated layered-image experiment; no normal renderer hooks"};
        std::string mode,pak,job,folder,variants,output;bool pictures=false;
        app.add_option("--mode",mode)->required()->check(CLI::IsMember({"capture","evaluate","self-test","export-live"}));
        app.add_option("--pak",pak);app.add_option("--job",job);app.add_option("--capture",folder);
        app.add_option("--variants",variants);app.add_option("--output",output);app.add_flag("--pictures",pictures);
        try {app.parse(argc,argv);} catch(const CLI::ParseError& e){return app.exit(e);}
        if(mode=="capture") layered_images::capture_job(pak,layered_images::read_json(job),output);
        else if(mode=="evaluate")layered_images::evaluate_job(folder,layered_images::read_json(variants),output,pictures);
        else if(mode=="export-live")layered_images::export_live_geometry(pak,layered_images::read_json(job),output);
        else layered_images::self_test();
        std::cout<<"PASS "<<mode<<" elapsedSeconds="<<layered_images::seconds(start)<<'\n';return 0;
    } catch(const std::exception& e) {
        std::cerr<<"FAIL "<<e.what()<<" elapsedSeconds="<<layered_images::seconds(start)<<'\n';return 1;
    }
}
