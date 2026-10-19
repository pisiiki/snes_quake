#include "experiment.hpp"
#include "sky.hpp"
#include "turbulence.hpp"

namespace layered_images {
namespace {
std::uint32_t packed(Rgb c) { return (std::uint32_t(c.r)<<16U)|(std::uint32_t(c.g)<<8U)|c.b; }
struct Rect { Vec3 lo, hi, normal; int axis; std::uint16_t id; };
struct Surface { double depth; Vec3 normal; std::uint32_t rgb; std::uint16_t face; };

class Scene {
    std::optional<SourceWorld> world;
    std::unique_ptr<Bvh> bvh;
    std::vector<Rect> rects;
    std::map<int,QuakeSkyTile> sky_tiles;
    std::string type;
    double time{};
public:
    Scene(const fs::path& pak, const Json& job, double scene_time) : type(job.value("case", "")), time(scene_time) {
        if (job.at("scene") == "quake") {
            const auto bytes=read_file(pak);
            const auto palette=parse_quake_palette(extract_pak_entry(bytes,"gfx/palette.lmp"));
            const auto colormap=parse_quake_colormap(extract_pak_entry(bytes,"gfx/colormap.lmp"));
            world.emplace(build_source_world(parse_bsp(extract_pak_entry(bytes,job.at("mapEntry").get<std::string>()),palette,colormap)));
            bvh=std::make_unique<Bvh>(world->triangles);
            for(std::size_t i=0;i<world->textures.size();++i)
                if(is_quake_sky_texture_name(world->textures[i].name))
                    sky_tiles.emplace(static_cast<int>(i),make_quake_sky_tile(world->textures[i],quake_sky_clock(time)));
        } else {
            add({-180,160,-32},{180,160,128},{0,-1,0},1);
            add({-180,-200,-32},{180,160,-32},{0,0,1},2);
            add({-180,-200,128},{180,160,128},{0,0,-1},2);
            add({-180,-200,-32},{-180,160,128},{1,0,0},0);
            add({180,-200,-32},{180,160,128},{-1,0,0},0);
            if(type=="doorway" || type=="opening-door") {
                add({-180,20,-32},{-20,20,128},{0,-1,0},1);
                add({20,20,-32},{180,20,128},{0,-1,0},1);
                add({-20,20,84},{20,20,128},{0,-1,0},1);
                if(type=="opening-door") {
                    const double lift=scene_time*220;
                    add({-20,20,-32+lift},{20,20,84+lift},{0,-1,0},1);
                }
            } else if(type=="layer-exhaustion") {
                for(int i=0;i<10;++i) {
                    const double y=-40+i*16.0;
                    const double half=8+i*2.0;
                    add({-half,y,-32},{half,y,100},{0,-1,0},1);
                }
            } else {
                const double shift=type=="moving-actor" ? scene_time*180 : 0;
                box({-10+shift,-10,-32},{10+shift,10,96});
            }
        }
    }
    void add(Vec3 lo,Vec3 hi,Vec3 normal,int axis) {
        rects.push_back({lo,hi,normal,axis,static_cast<std::uint16_t>(rects.size())});
    }
    void box(Vec3 lo,Vec3 hi) {
        add(lo,{hi.x,lo.y,hi.z},{0,-1,0},1);
        add({lo.x,hi.y,lo.z},hi,{0,1,0},1);
        add(lo,{lo.x,hi.y,hi.z},{-1,0,0},0);
        add({hi.x,lo.y,lo.z},hi,{1,0,0},0);
        add({lo.x,lo.y,hi.z},hi,{0,0,1},2);
    }
    std::vector<std::uint8_t> visible(const ViewTransform& view) const {
        std::vector<std::uint8_t> mask;
        if(world) {
            mask.resize(static_cast<std::size_t>(world->face_count));
            for(std::size_t i=0;i<mask.size();++i)
                mask[i]=dot(view.origin,world->visibility_planes[i].normal)-world->visibility_planes[i].distance>kFaceVisibilityEpsilon;
        }
        return mask;
    }
    std::vector<Surface> trace(const Ray& ray,int layers,std::span<const std::uint8_t> mask,
                              const ViewTransform& view,double screen_x,double screen_y) const {
        std::vector<Surface> hits;
        if(world) {
            double offset=0;
            for(int l=0;l<layers;++l) {
                const auto hit=bvh->nearest({ray.origin+ray.direction*offset,ray.direction},mask);
                if(hit.face==kMissFace) break;
                const double depth=offset+hit.depth;
                auto sample=sample_exact_texture(*world,hit.face,ray);
                auto index=sample.index;
                const int texture_id=world->texture_infos.at(static_cast<std::size_t>(world->face_texture_infos.at(hit.face))).texture_id;
                const auto& texture=world->textures.at(static_cast<std::size_t>(texture_id));
                // Freeze animated textures at the declared source scene time.
                if(texture.turbulent) {
                    index=sample_quake_turbulent_texture(texture,static_cast<int>(sample.s*16),static_cast<int>(sample.t*16),
                        quake_turbulence_phase(time),world->turbulence_table);
                } else if(is_quake_sky_texture_name(texture.name)) {
                    const double u=screen_x-.5,v=screen_y-.5;
                    auto adjusted=view;
                    adjusted.forward=view.forward+view.screen_right*(2*(u-std::floor(u))/85)-view.up*(2*(v-std::floor(v))/85);
                    const auto st=quake_sky_uv_to_st(adjusted,static_cast<int>(std::floor(u)),static_cast<int>(std::floor(v)),quake_sky_clock(time));
                    index=quake_sky_sample(sky_tiles.at(texture_id),st[0],st[1]);
                } else {
                    index=remap_texture_index(*world,index,sample_bsp_lightmap_level(*world,hit.face,sample.s,sample.t),0);
                }
                hits.push_back({depth,world->visibility_planes[hit.face].normal,packed(world->texture_palette[index]),hit.face});
                offset=depth+1e-4;
            }
        } else {
            for(const auto& r:rects) {
                if(dot(ray.direction,r.normal)>=-1e-9) continue;
                const double d=(r.lo[r.axis]-ray.origin[r.axis])/ray.direction[r.axis];
                if(d<=1e-6) continue;
                const auto point=ray.origin+ray.direction*d;
                bool inside=true;
                for(int a=0;a<3;++a) if(a!=r.axis) inside=inside && point[a]>=r.lo[a] && point[a]<=r.hi[a];
                if(!inside) continue;
                const int a=(r.axis+1)%3,b=(r.axis+2)%3;
                const double phase=type=="animated-surface" ? time*80 : 0;
                const int check=(static_cast<int>(std::floor((point[a]+phase)/8))^static_cast<int>(std::floor(point[b]/8)))&1;
                const int level=check ? 210:90;
                const auto rgb=packed({static_cast<std::uint8_t>(level),static_cast<std::uint8_t>(45+r.id*17%140),
                    static_cast<std::uint8_t>(220-level/2)});
                hits.push_back({d,r.normal,rgb,r.id});
            }
            std::stable_sort(hits.begin(),hits.end(),[](const Surface& a,const Surface& b){return a.depth<b.depth;});
            if(hits.size()>static_cast<std::size_t>(layers)) hits.resize(static_cast<std::size_t>(layers));
        }
        return hits;
    }
    std::optional<ReferenceFrame> original_frame(const SourceCamera& camera) const {
        if(!world) return {};
        auto frame=render_source_reference(*world,*bvh,camera,false);
        const auto sky=render_quake_sky_presentation(frame.lightmap_texture_indices,frame.faces,frame.entities,
            *world,source_view_transform(camera),time,"experiment-frozen");
        frame.lightmap_texture_indices=sky.indices;
        return frame;
    }
    std::uint32_t original_color(const ReferenceFrame& frame,std::size_t pixel) const {
        return frame.faces[pixel]==kMissFace ? 0:packed(world->texture_palette[frame.lightmap_texture_indices[pixel]]);
    }
    bool special(std::uint16_t face) const {
        if(!world || face==kMissFace) return false;
        const auto& texture=world->textures.at(static_cast<std::size_t>(world->texture_infos.at(
            static_cast<std::size_t>(world->face_texture_infos.at(face))).texture_id));
        return texture.turbulent;
    }
    void finish_sky(std::vector<std::uint32_t>& rgb,const std::vector<std::uint16_t>& faces,const ViewTransform& view) const {
        if(!world || sky_tiles.empty()) return;
        const std::vector<std::uint8_t> indices(kLogicalPixels);
        const std::vector<std::uint16_t> entities(kLogicalPixels);
        const auto sky=render_quake_sky_presentation(indices,faces,entities,*world,view,time,"experiment-frozen");
        for(int y=0;y<height;++y)for(int x=0;x<width;++x) {
            const auto p=logical_pixel_index(x,y),face=static_cast<std::size_t>(faces[p]);
            if(face<world->face_sky_mask.size() && world->face_sky_mask[face])
                rgb[static_cast<std::size_t>(y*width+x)]=packed(world->texture_palette[sky.indices[p]]);
        }
    }
};

SourceCamera camera(const Json& p) {
    return {{p.at("position")[0],p.at("position")[1],p.at("position")[2]},p.at("pitch"),p.at("yaw"),p.at("roll")};
}
Ray ray_at(const ViewTransform& view,double x,double y) {
    return {view.origin,view.forward+view.screen_right*((x-42)/64)+view.up*((37-y)/64)};
}
std::vector<std::uint32_t> fresh(const Scene& scene,const ViewTransform& view) {
    const auto mask=scene.visible(view);
    std::vector<std::uint32_t> pixels(width*height);
    std::vector<std::uint16_t> faces(kLogicalPixels,kMissFace);
    for(int y=0;y<height;++y) for(int x=0;x<width;++x) {
        const auto hits=scene.trace(ray_at(view,x+.5,y+.5),1,mask,view,x+.5,y+.5);
        if(!hits.empty()) {pixels[static_cast<std::size_t>(y*width+x)]=hits[0].rgb;faces[logical_pixel_index(x,y)]=hits[0].face;}
    }
    scene.finish_sky(pixels,faces,view);
    return pixels;
}
}

void capture_job(const fs::path& pak,const Json& job,const fs::path& output) {
    const auto start=Clock::now();
    const RenderViewportScope scope(RenderScale::X3);
    fs::create_directories(output);
    const Scene scene(pak,job,0);
    const auto source_camera=camera(job.at("cameras")[0]);
    Capture c;
    c.view=source_view_transform(source_camera);
    c.padding=job.at("capture").at("padding"); c.density=job.at("capture").at("density"); c.layers=job.at("capture").at("layers");
    c.w=(width+2*c.padding)*c.density; c.h=(height+2*c.padding)*c.density;
    const auto refresh_start=Clock::now();
    c.samples.resize(static_cast<std::size_t>(c.w*c.h*c.layers));
    const auto mask=scene.visible(c.view);
    const auto capture_start=Clock::now();
    std::vector<std::size_t> layer_counts(static_cast<std::size_t>(c.layers));
    for(int y=0;y<c.h;++y) for(int x=0;x<c.w;++x) {
        const double u=(x+.5)/c.density-c.padding,v=(y+.5)/c.density-c.padding;
        const auto hits=scene.trace(ray_at(c.view,u,v),c.layers,mask,c.view,u,v);
        for(std::size_t l=0;l<hits.size();++l) {
            const auto& h=hits[l];
            c.samples[(l*static_cast<std::size_t>(c.h)+static_cast<std::size_t>(y))*static_cast<std::size_t>(c.w)+static_cast<std::size_t>(x)]={
                static_cast<float>(h.depth),{static_cast<float>(h.normal.x),static_cast<float>(h.normal.y),static_cast<float>(h.normal.z)},h.rgb,h.face,0};
            ++layer_counts[l];
        }
    }
    const double capture_seconds=seconds(capture_start);
    const auto fresh_start=Clock::now();
    c.source=fresh(scene,c.view);
    const double fresh_seconds=seconds(fresh_start);
    // Match the production sky span sampler at retained display texel centres.
    for(int y=0;y<height;++y)for(int x=0;x<width;++x) {
        const int xx=(x+c.padding)*c.density+c.density/2,yy=(y+c.padding)*c.density+c.density/2;
        c.samples[static_cast<std::size_t>(yy*c.w+xx)].rgb=c.source[static_cast<std::size_t>(y*width+x)];
    }
    const double refresh_seconds=seconds(refresh_start);
    std::ofstream raw(output/"samples.bin",std::ios::binary);
    raw.write(reinterpret_cast<const char*>(c.samples.data()),static_cast<std::streamsize>(c.samples.size()*sizeof(Sample)));
    if(!raw) fail("cannot write samples");
    save_rgb(output/"source.rgb",c.source);
    std::size_t parity_pixels=0,parity_mismatches=0,special_pixels=0;
    const auto original_start=Clock::now();
    if(const auto original=scene.original_frame(source_camera)) {
        for(int y=0;y<height;++y) for(int x=0;x<width;++x) {
            const auto p=logical_pixel_index(x,y);
            if(scene.special(original->faces[p])) {++special_pixels;continue;}
            ++parity_pixels;
            parity_mismatches+=c.source[static_cast<std::size_t>(y*width+x)]!=scene.original_color(*original,p);
        }
    }
    const double original_seconds=seconds(original_start);
    if(parity_mismatches) fail("source shading differs from original reference");
    Json targets=Json::array();
    const WarpSettings settings{false,192,true,32,{213,205,437}};
    const std::vector<std::uint32_t> white(width*height,0xffffff);
    for(std::size_t age=0;age<job.at("cameras").size();++age) {
        const auto view=source_view_transform(camera(job.at("cameras")[age]));
        const auto target_start=Clock::now();
        const auto pixels=fresh(scene,view);
        const double target_seconds=seconds(target_start);
        save_rgb(output/("target-"+std::to_string(age)+".rgb"),present_x3(pixels,{}));
        const auto hdma_start=Clock::now();
        const auto bands=hdma_camera_warp(view,c.view,settings);
        const auto baseline=present_hdma_x3(c.source,bands);
        const double hdma_seconds=seconds(hdma_start);
        save_rgb(output/("baseline-"+std::to_string(age)+".rgb"),baseline);
        save_rgb(output/("baseline-mask-"+std::to_string(age)+".rgb"),present_hdma_x3(white,bands));
        if(job.value("dynamic",false)) {
            const Scene changed(pak,job,static_cast<double>(age)/30);
            save_rgb(output/("dynamic-"+std::to_string(age)+".rgb"),present_x3(fresh(changed,view),{}));
        }
        targets.push_back({{"age",age},{"view",view_json(view)},{"freshSeconds",target_seconds},{"hdmaSeconds",hdma_seconds}});
    }
    save_json(output/"capture.json",{{"schema","layered-image-capture-v1"},{"job",job},{"view",view_json(c.view)},
        {"width",c.w},{"height",c.h},{"sampleBytes",sizeof(Sample)},{"layerCounts",layer_counts},
        {"captureSeconds",capture_seconds},{"freshSeconds",fresh_seconds},{"originalRenderSeconds",original_seconds},
        {"retainedFrameGenerationSeconds",refresh_seconds},
        {"parityPixels",parity_pixels},{"parityMismatches",parity_mismatches},{"specialSurfacePixels",special_pixels},
        {"targets",targets},{"elapsedSeconds",seconds(start)}});
}

Capture load_capture(const fs::path& output) {
    Capture c; c.metadata=read_json(output/"capture.json");
    const auto& spec=c.metadata.at("job").at("capture");
    c.padding=spec.at("padding"); c.density=spec.at("density"); c.layers=spec.at("layers");
    c.w=c.metadata.at("width"); c.h=c.metadata.at("height"); c.view=json_view(c.metadata.at("view"));
    c.samples.resize(static_cast<std::size_t>(c.w*c.h*c.layers));
    const auto bytes=fs::file_size(output/"samples.bin");
    if(bytes!=c.samples.size()*sizeof(Sample)) fail("invalid capture byte count");
    std::ifstream raw(output/"samples.bin",std::ios::binary);
    raw.read(reinterpret_cast<char*>(c.samples.data()),static_cast<std::streamsize>(bytes));
    if(!raw) fail("cannot read capture");
    c.source=load_rgb(output/"source.rgb");
    return c;
}
} // namespace layered_images
